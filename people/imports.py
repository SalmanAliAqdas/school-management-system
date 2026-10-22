"""Bounded, owner-bound, single-use and atomic CSV admission staging."""

import csv
import io
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_event
from core.operations import require_capability

from .forms import AdmissionForm
from .models import AdmissionImport, Enrollment
from .services import admit_student, check_identity, lock_year

CSV_COLUMNS = [
    "external_reference",
    "first_name",
    "last_name",
    "admission_date",
    "date_of_birth",
    "academic_year",
    "section",
    "started_on",
    "roll_number",
    "guardian",
    "relationship",
]
REQUIRED_COLUMNS = set(CSV_COLUMNS) - {"roll_number", "guardian", "relationship"}


def import_permission(actor):
    require_capability(actor, "people.import_students", student_scope=True)
    require_capability(actor, "people.add_student", student_scope=True)


def validate_rows(rows):
    results, identities, references, rolls = [], set(), set(), set()
    for number, row in enumerate(rows, start=2):
        form = AdmissionForm(row)
        errors = []
        if not form.is_valid():
            errors.extend(
                f"{field}: {', '.join(messages)}" for field, messages in form.errors.items()
            )
        else:
            data = form.cleaned_data
            try:
                check_identity(data)
            except ValidationError as exc:
                errors.extend(exc.messages)
            if not data.get("external_reference"):
                errors.append(
                    "external_reference: A stable source reference is required "
                    "for safe re-import detection."
                )
            identity = (
                data["first_name"].casefold(),
                data["last_name"].casefold(),
                str(data["date_of_birth"]),
            )
            reference = data.get("external_reference", "").casefold()
            if identity in identities or reference in references:
                errors.append("Duplicate student or source reference inside this CSV.")
            identities.add(identity)
            references.add(reference)
            if data.get("roll_number"):
                key = (data["academic_year"].pk, data["section"].pk, data["roll_number"])
                if (
                    key in rolls
                    or Enrollment.objects.filter(
                        academic_year=data["academic_year"],
                        section=data["section"],
                        roll_number=data["roll_number"],
                        is_active=True,
                    ).exists()
                ):
                    errors.append("This active section roll number is already in use.")
                rolls.add(key)
        results.append({"number": number, "row": row, "errors": errors})
    return results


@transaction.atomic
def preview_import(actor, upload):
    import_permission(actor)
    if upload.size > 1024 * 1024:
        raise ValidationError("CSV files must be no larger than 1 MB.")
    try:
        content = upload.read(1024 * 1024 + 1).decode("utf-8-sig")
        if "\x00" in content:
            raise ValueError
        reader = csv.DictReader(io.StringIO(content), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValidationError("CSV headers are missing or duplicated.")
        headers = set(reader.fieldnames)
        if REQUIRED_COLUMNS - headers or headers - set(CSV_COLUMNS):
            raise ValidationError(
                "Use the template headers. Required: " + ", ".join(sorted(REQUIRED_COLUMNS))
            )
        rows = []
        for row in reader:
            if len(rows) >= 500:
                raise ValidationError("Import at most 500 students at a time.")
            if None in row or any(value is None for value in row.values()):
                raise ValidationError("A CSV row has an incorrect number of columns.")
            rows.append({key: value.strip() for key, value in row.items()})
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise ValidationError("Upload a well-formed UTF-8 CSV using the template.") from exc
    if not rows:
        raise ValidationError("The CSV contains no student rows.")
    results = validate_rows(rows)
    batch = None
    if not any(result["errors"] for result in results):
        if any(row.get("guardian") for row in rows):
            require_capability(actor, "people.add_guardianstudent", student_scope=True)
        batch = AdmissionImport.objects.create(
            actor=actor, rows=rows, expires_at=timezone.now() + timedelta(minutes=30)
        )
        record_event("admissions.import_previewed", actor=actor, target=batch.pk)
    return results, batch


@transaction.atomic
def confirm_import(actor, pk):
    import_permission(actor)
    batch = AdmissionImport.objects.select_for_update().get(pk=pk)
    if batch.actor_id != actor.pk:
        raise PermissionDenied
    if batch.confirmed_at or batch.expires_at <= timezone.now():
        raise ValidationError(
            "This preview has expired or was already imported. Upload the CSV again."
        )
    for year_id in sorted({int(row["academic_year"]) for row in batch.rows}):
        lock_year(year_id)
    results = validate_rows(batch.rows)
    if any(result["errors"] for result in results):
        raise ValidationError(
            "School records changed after preview. Upload the CSV again to review current "
            "validation results. No students were imported."
        )
    count = len(batch.rows)
    for row in batch.rows:
        form = AdmissionForm(row)
        if not form.is_valid():
            raise ValidationError("A row changed during confirmation. No students were imported.")
        data = form.cleaned_data
        admit_student(
            actor,
            data={name: data[name] for name in form._meta.fields if name != "photo"},
            academic_year=data["academic_year"],
            section=data["section"],
            started_on=data["started_on"],
            roll_number=data.get("roll_number", ""),
            guardians=[(data["guardian"], data["relationship"])] if data.get("guardian") else [],
        )
    batch.confirmed_at = timezone.now()
    batch.rows = []
    batch.save(update_fields=["confirmed_at", "rows", "updated_at"])
    record_event("admissions.import_confirmed", actor=actor, target=batch.pk)
    return count
