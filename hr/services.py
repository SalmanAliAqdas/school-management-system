from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_event
from learning.uploads import read_private_upload

from .models import Employee, EmploymentRecord, StaffDocument


def require_hr(actor, employee=None, *, manage=False):
    own = employee and employee.user_id == actor.pk
    permission = "hr.manage_hr" if manage else "hr.view_all_hr"
    if not actor.is_active or (not own and not actor.has_perm(permission)):
        raise PermissionDenied


@transaction.atomic
def employment_change(actor, employee, **values):
    require_hr(actor, employee, manage=True)
    current = employee.employment_records.select_for_update().filter(ends_on__isnull=True).first()
    start = values["starts_on"]
    if current:
        if start <= current.starts_on:
            raise ValidationError("A new employment record must begin after the current record.")
        current.ends_on = start - timezone.timedelta(days=1)
        current.reason = values.get("reason", "Employment detail changed")
        current.save(update_fields=["ends_on", "reason", "updated_at"])
    row = EmploymentRecord.objects.create(employee=employee, **values)
    employee.status = "active"
    employee.save(update_fields=["status", "updated_at"])
    record_event("hr.employment_changed", actor=actor, target=row.pk)
    return row


@transaction.atomic
def end_employment(actor, employee_id, day, reason, *, terminated=False):
    employee = Employee.objects.select_for_update().get(pk=employee_id)
    require_hr(actor, employee, manage=True)
    row = employee.employment_records.select_for_update().filter(ends_on__isnull=True).first()
    if not row or day < row.starts_on or not reason.strip():
        raise ValidationError("A current employment record, valid date and reason are required.")
    row.ends_on, row.reason = day, reason
    row.save(update_fields=["ends_on", "reason", "updated_at"])
    employee.status = "terminated" if terminated else "resigned"
    employee.save(update_fields=["status", "updated_at"])
    record_event("hr.employment_ended", actor=actor, target=row.pk)
    return row


@transaction.atomic
def upload_document(actor, employee, upload, *, kind, title, expires_on=None):
    require_hr(actor, employee, manage=True)
    data = read_private_upload(upload)
    row = StaffDocument.objects.create(
        employee=employee,
        kind=kind,
        title=title,
        expires_on=expires_on,
        uploaded_by=actor,
        filename=data["filename"],
        content_type=data["content_type"],
        content=data["data"],
    )
    record_event("hr.document_uploaded", actor=actor, target=row.pk)
    return row


def leave_balance(employee, policy, year):
    from attendance.models import LeaveRequest

    entitlement = employee.leave_entitlements.get(policy=policy, year=year)
    identity = {"staff": employee.staff} if employee.staff_id else {"teacher": employee.teacher}
    used = 0
    for leave in LeaveRequest.objects.filter(
        **identity,
        kind=policy.kind,
        state="approved",
        starts_on__year=year,
    ):
        used += (leave.ends_on - leave.starts_on).days + 1
    return entitlement.days - used
