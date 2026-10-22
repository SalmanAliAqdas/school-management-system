"""Authorized year-serialized examination writes and immutable publication history."""

import base64
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from academics.models import AcademicYear, ClassSubject
from attendance.calendar import SchoolCalendar, school_now
from audit.services import record_event
from core.models import SchoolSettings
from people.models import Enrollment, GuardianStudent

from .calculations import (
    aggregate_candidate,
    calculate_candidate,
    validate_policy,
    validate_weights,
)
from .models import (
    Assessment,
    AssessmentType,
    CandidateAmendment,
    ExamCandidate,
    ExamCohort,
    ExamController,
    ExaminationSettings,
    ExamNotification,
    ExamRoom,
    ExamSchedule,
    ExamSession,
    ExamSubject,
    GradeBand,
    GradingPolicy,
    Invigilation,
    MarkEntry,
    MarkSheet,
    PromotionRecommendation,
    PublishedResult,
    ResultCorrection,
    ResultEvent,
    ResultPublication,
    SessionContribution,
)
from .selectors import can_oversee, capable, sheets_visible_to, subjects_visible_to


def school_zone():
    return school_now().tzinfo


def require(user, capability, session=None):
    if not capable(user, capability) or (session is not None and not can_oversee(user, session)):
        raise PermissionDenied


def lock_session(pk, *, historical=False):
    year_id = ExamSession.objects.values_list("academic_year_id", flat=True).get(pk=pk)
    year = AcademicYear.objects.select_for_update().get(pk=year_id)
    if not historical and year.status != "open":
        raise ValidationError(
            "This academic year is closed; new examination changes are protected."
        )
    return (
        ExamSession.objects.select_for_update(of=("self",))
        .select_related("policy", "academic_year", "term")
        .get(pk=pk)
    )


def event(actor, session, action, reason, *, sheet=None, public=False):
    row = ResultEvent.objects.create(
        session=session, actor=actor, action=action, reason=reason, sheet=sheet
    )
    record_event(f"exam.{action}", actor=actor, target=f"{session.pk}:{row.pk}")
    recipients = set()
    if public:
        candidates = list(session.candidates.select_related("student"))
        links = {}
        for student_id, recipient in GuardianStudent.objects.filter(
            student_id__in=[c.student_id for c in candidates], guardian__user__is_active=True
        ).values_list("student_id", "guardian__user_id"):
            links.setdefault(student_id, set()).add(recipient)
        pairs = set()
        for candidate in candidates:
            recipients_for_child = links.get(candidate.student_id, set()).copy()
            if candidate.student.user_id:
                recipients_for_child.add(candidate.student.user_id)
            pairs.update(
                (candidate.pk, recipient) for recipient in recipients_for_child if recipient
            )
        active = set(
            get_user_model()
            .objects.filter(is_active=True, pk__in=[p[1] for p in pairs])
            .values_list("pk", flat=True)
        )
        ExamNotification.objects.bulk_create(
            [
                ExamNotification(recipient_id=recipient, candidate_id=candidate, event=row)
                for candidate, recipient in pairs
                if recipient in active
            ],
            ignore_conflicts=True,
        )
    else:
        recipients.update(session.controllers.filter(is_active=True).values_list("pk", flat=True))
        if sheet and sheet.submitted_by_id:
            recipients.add(sheet.submitted_by_id)
        if action == "review":
            recipients.update(
                get_user_model()
                .objects.filter(
                    is_active=True,
                    groups__permissions__content_type__app_label="examinations",
                    groups__permissions__codename="approve_results",
                )
                .values_list("pk", flat=True)
            )
        ExamNotification.objects.bulk_create(
            [ExamNotification(recipient_id=pk, event=row) for pk in recipients],
            ignore_conflicts=True,
        )
    return row


def setup_session_for(instance):
    if isinstance(instance, ExamSession):
        return instance
    if isinstance(instance, (ExamCohort, ExamController, SessionContribution)):
        return instance.session
    if isinstance(instance, ExamSubject):
        return instance.cohort.session
    if isinstance(instance, Assessment):
        return instance.exam_subject.cohort.session
    return None


@transaction.atomic
def save_setup(actor, instance):
    """Instances come from explicit-field forms; recheck all relationships under locks."""
    require(actor, "manage_examinations")
    original = type(instance).objects.filter(pk=instance.pk).first() if instance.pk else None
    session = setup_session_for(instance)
    if session is not None:
        if isinstance(instance, ExamSession) and original is None:
            year = AcademicYear.objects.select_for_update().get(pk=instance.academic_year_id)
            if year.status != "open":
                raise ValidationError("Choose an open academic year.")
            instance.created_by = actor
            instance.state = "draft"
        else:
            session = lock_session(session.pk)
            require(actor, "manage_examinations", session)
            if session.state != "draft":
                raise ValidationError(
                    "Setup is frozen once entry opens. Create a new session for new rules."
                )
            if original and setup_session_for(original).pk != session.pk:
                raise ValidationError(
                    "An existing configuration cannot be moved to another session."
                )
        year = (
            instance.academic_year if isinstance(instance, ExamSession) else session.academic_year
        )
    elif isinstance(instance, (GradingPolicy, GradeBand)):
        policy = instance if isinstance(instance, GradingPolicy) else instance.policy
        year = AcademicYear.objects.select_for_update().get(pk=policy.academic_year_id)
        if year.status != "open" or policy.sessions.exclude(state="draft").exists():
            raise ValidationError(
                "A used or closed grading policy is immutable. Create a new policy version."
            )
    else:
        # Serialize global type/room/settings edits with academic services.
        SchoolSettings.objects.get_or_create(pk=1)
        SchoolSettings.objects.select_for_update().get(pk=1)
        if (
            original
            and isinstance(instance, AssessmentType)
            and (instance.examsession_set.exists() or instance.assessment_set.exists())
        ):
            raise ValidationError("This assessment type is in use; create another type instead.")
        if original and isinstance(instance, ExamRoom) and instance.examschedule_set.exists():
            raise ValidationError("This room has examination history; create another room instead.")
        year = None
    if isinstance(instance, ExamSession):
        if instance.policy.academic_year_id != year.pk:
            raise ValidationError("The grading policy must belong to the same academic year.")
        if not year.starts_on <= instance.starts_on <= instance.ends_on <= year.ends_on:
            raise ValidationError("Examination dates must fall within the academic year.")
        if instance.term_id and (
            instance.term.academic_year_id != year.pk
            or not instance.term.starts_on
            <= instance.starts_on
            <= instance.ends_on
            <= instance.term.ends_on
        ):
            raise ValidationError("Choose a matching term and dates inside that term.")
        if instance.report_kind == "term" and not instance.term_id:
            raise ValidationError("A term report requires a term.")
        if instance.retake_of_id:
            source = instance.retake_of
            if not can_oversee(actor, source):
                raise PermissionDenied
            if (
                source.pk == instance.pk
                or source.academic_year_id != year.pk
                or source.report_kind != "assessment"
                or instance.report_kind != "assessment"
                or source.state not in ("published", "archived")
                or source.ends_on >= instance.starts_on
            ):
                raise ValidationError(
                    "A supplementary assessment must follow a published original assessment "
                    "in the same year."
                )
        if original and instance.academic_year_id != original.academic_year_id:
            raise ValidationError("The academic year cannot be changed after creation.")
    if (
        isinstance(instance, ExamSubject)
        and not ClassSubject.objects.filter(
            academic_year=year,
            school_class=instance.cohort.section.school_class,
            subject=instance.subject,
        ).exists()
    ):
        raise ValidationError("Assign this subject to the class and academic year first.")
    if (
        isinstance(instance, ExamCohort)
        and original
        and original.section_id != instance.section_id
        and original.subjects.exists()
    ):
        raise ValidationError(
            "This cohort already has subjects. Create another cohort for a different section."
        )
    if isinstance(instance, Assessment) and session.report_kind != "assessment":
        raise ValidationError(
            "Term and annual reports use source sessions rather than new marks assessments."
        )
    if isinstance(instance, ExamController) and (
        not instance.user.is_active or not instance.user.has_perm("examinations.review_results")
    ):
        raise ValidationError("Choose an active account with examination review permission.")
    if isinstance(instance, SessionContribution):
        source = instance.source
        if not can_oversee(actor, source):
            raise PermissionDenied
        related_sources = Q(source__retake_of=source)
        if source.retake_of_id:
            related_sources |= Q(source_id=source.retake_of_id)
        if session.contributions.exclude(pk=instance.pk).filter(related_sources).exists():
            raise ValidationError(
                "Choose the original or its supplementary replacement, rather than counting both."
            )
        if (
            session.report_kind == "assessment"
            or source.academic_year_id != year.pk
            or source.pk == session.pk
        ):
            raise ValidationError(
                "Sources must be other sessions in the same academic year for a term/annual report."
            )
        if source.report_kind == "annual" or (
            session.report_kind == "term"
            and (source.report_kind != "assessment" or source.term_id != session.term_id)
        ):
            raise ValidationError(
                "Term reports use assessments from that term; "
                "annual reports use assessments or term reports."
            )
        if source.state not in ("published", "archived") or source.ends_on > session.ends_on:
            raise ValidationError(
                "Choose an already published source ending on or before this report."
            )
    instance.full_clean()
    instance.save()
    if isinstance(instance, ExamSession) and original is None and capable(actor, "review_results"):
        ExamController.objects.get_or_create(session=instance, user=actor)
    record_event(
        "exam.setup_saved", actor=actor, target=f"{instance._meta.model_name}:{instance.pk}"
    )
    return instance


@transaction.atomic
def delete_setup(actor, instance):
    require(actor, "manage_examinations")
    session = setup_session_for(instance)
    if session:
        session = lock_session(session.pk)
        require(actor, "manage_examinations", session)
        if session.state != "draft":
            raise ValidationError("Only unused draft configuration can be removed.")
    elif isinstance(instance, GradeBand):
        AcademicYear.objects.select_for_update().get(pk=instance.policy.academic_year_id)
        if instance.policy.sessions.exclude(state="draft").exists():
            raise ValidationError("Used grade bands are protected.")
    else:
        raise ValidationError("This record cannot be removed through examination setup.")
    record_event(
        "exam.setup_removed", actor=actor, target=f"{instance._meta.model_name}:{instance.pk}"
    )
    instance.delete()


@transaction.atomic
def save_schedule(actor, *, assessment_id, starts_at, ends_at, room=None, invigilators=()):
    assessment = Assessment.objects.select_related("exam_subject__cohort__session").get(
        pk=assessment_id
    )
    session = lock_session(assessment.exam_subject.cohort.session_id)
    require(actor, "manage_examinations", session)
    if (
        session.state not in ("draft", "open")
        or MarkSheet.objects.filter(assessment__exam_subject__cohort__session=session)
        .exclude(state="draft")
        .exists()
    ):
        raise ValidationError("Schedules are protected once any marks are submitted.")
    local_start, local_end = starts_at.astimezone(school_zone()), ends_at.astimezone(school_zone())
    if (
        local_start.date() != local_end.date()
        or ends_at <= starts_at
        or not (session.starts_on <= local_start.date() <= session.ends_on)
    ):
        raise ValidationError(
            "Use ordered times on one school date within the examination session."
        )
    calendar = SchoolCalendar(session.academic_year)
    reason = calendar.reason(local_start.date())
    if reason and calendar.policy(local_start.date()):
        raise ValidationError(f"Choose a working academic date: {reason}.")
    teachers = list(invigilators)
    if len({p.pk for p in teachers}) != len(teachers) or any(not p.is_active for p in teachers):
        raise ValidationError("Choose distinct active invigilators.")
    slot = ExamSchedule.objects.filter(assessment=assessment).first()
    if slot:
        slot.duties.all().delete()
    else:
        slot = ExamSchedule(assessment=assessment)
    slot.section = assessment.exam_subject.cohort.section
    slot.school_class = slot.section.school_class
    slot.starts_at, slot.ends_at, slot.room = starts_at, ends_at, room
    try:
        with transaction.atomic():
            slot.full_clean()
            slot.save()
            for teacher in teachers:
                duty = Invigilation(
                    schedule=slot, teacher=teacher, starts_at=starts_at, ends_at=ends_at
                )
                duty.full_clean()
                duty.save()
    except IntegrityError as exc:
        raise ValidationError(
            "This time conflicts with a class, section, room or invigilator."
        ) from exc
    event(actor, session, "schedule_saved", "Date sheet updated")
    return slot


def validate_configuration(session):
    validate_policy(session.policy)
    cohorts = list(session.cohorts.select_related("section"))
    if not cohorts:
        raise ValidationError("Add at least one class/section cohort.")
    for cohort in cohorts:
        subjects = validate_weights(
            cohort.subjects.select_related("subject"), f"{cohort.section} subject"
        )
        for subject in subjects:
            if session.report_kind == "assessment":
                validate_weights(subject.assessments.all(), str(subject.subject))
    if session.report_kind != "assessment":
        validate_weights(session.contributions.all(), "Source session")
        for contribution in session.contributions.select_related("source"):
            if contribution.source.state not in ("published", "archived"):
                raise ValidationError("Every source session must be published.")
            if set(session.cohorts.values_list("section_id", flat=True)) - set(
                contribution.source.cohorts.values_list("section_id", flat=True)
            ):
                raise ValidationError("Each source must cover all report sections.")
    return cohorts


def freeze_roster(session, cohorts):
    for cohort in cohorts:
        enrollments = Enrollment.objects.filter(
            academic_year=session.academic_year,
            section=cohort.section,
            started_on__lte=session.eligibility_on,
        ).filter(Q(ended_on__isnull=True) | Q(ended_on__gte=session.eligibility_on))
        if session.retake_of_id:
            enrollments = enrollments.filter(
                student_id__in=session.retake_of.candidates.values("student_id")
            )
        if not enrollments.exists():
            raise ValidationError(
                f"{cohort.section} has no eligible enrollments on the roster date."
            )
        ExamCandidate.objects.bulk_create(
            [
                ExamCandidate(session=session, cohort=cohort, enrollment=e, student_id=e.student_id)
                for e in enrollments
            ]
        )
    MarkSheet.objects.bulk_create(
        [
            MarkSheet(assessment=a)
            for a in Assessment.objects.filter(exam_subject__cohort__session=session)
        ]
    )


@transaction.atomic
def session_action(actor, session_id, action, *, expected_version, reason):
    session = lock_session(session_id, historical=action in ("archive",))
    require(
        actor,
        {
            "approve": "approve_results" if session.policy.principal_approval else "review_results",
            "publish": "publish_results",
        }.get(action, "review_results" if action == "review" else "manage_examinations"),
        session,
    )
    if not reason.strip():
        raise ValidationError("Give a reason for this examination transition.")
    if expected_version != session.version:
        raise ValidationError("This session changed. Reload before trying again.")
    sheets = MarkSheet.objects.filter(assessment__exam_subject__cohort__session=session)
    if action == "open" and session.state == "draft":
        freeze_roster(session, validate_configuration(session))
        session.state = "open"
    elif action == "close" and session.state == "open":
        session.state = "closed"
    elif action == "reopen" and session.state in ("closed", "review"):
        session.state = "open"
    elif action == "review" and session.state == "closed":
        if session.report_kind == "assessment" and (
            not sheets.exists() or sheets.exclude(state="approved").exists()
        ):
            raise ValidationError("Every marks sheet needs independent controller approval first.")
        validate_configuration(session)
        session.state = "review"
    elif action == "approve" and session.state == "review":
        if session.policy.principal_approval and not actor.has_perm("examinations.approve_results"):
            raise PermissionDenied
        if session.policy.independent_review and sheets.filter(submitted_by=actor).exists():
            raise ValidationError("An independent approver must approve this session.")
        if (
            session.policy.independent_review
            and session.report_kind != "assessment"
            and session.events.filter(action="review", actor=actor).exists()
        ):
            raise ValidationError("An independent approver must approve this consolidated report.")
        session.state, session.approved_by, session.approved_at = "approved", actor, timezone.now()
    elif action == "publish" and session.state == "approved":
        if session.ends_on > school_now().date():
            raise ValidationError(
                "Publish after the examination window has ended in the school timezone."
            )
        make_publication(actor, session, reason)
        session.state = "published"
    elif action == "archive" and session.state == "published":
        session.state = "archived"
    else:
        raise ValidationError("This transition is not allowed from the current examination state.")
    session.version += 1
    session.full_clean()
    session.save()
    event(actor, session, action, reason, public=action == "publish")
    return session


def validate_mark(assessment, status, marks, remarks=""):
    if status not in MarkEntry.Status.values:
        raise ValidationError("Choose a supported assessment status.")
    if status == "assessed":
        try:
            value = Decimal(str(marks))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Enter valid decimal marks for an assessed student.") from exc
        if (
            not value.is_finite()
            or value < 0
            or value > assessment.max_marks
            or value != value.quantize(Decimal("0.001"))
        ):
            raise ValidationError(
                f"Marks must be 0–{assessment.max_marks}, with at most three decimal places."
            )
    else:
        if marks not in (None, ""):
            raise ValidationError(
                "Only assessed students receive marks; other statuses require an empty mark."
            )
        value = None
    if status in ("exempt", "withheld") and not remarks.strip():
        raise ValidationError("Explain an exemption or withheld assessment in the remarks.")
    if len(remarks) > 500:
        raise ValidationError("Use at most 500 characters for assessment remarks.")
    return value


@transaction.atomic
def save_marks(actor, sheet_id, rows, *, expected_version, submit=False):
    initial = MarkSheet.objects.select_related("assessment__exam_subject__cohort").get(pk=sheet_id)
    session = lock_session(initial.assessment.exam_subject.cohort.session_id)
    if (
        not capable(actor, "enter_marks")
        or not subjects_visible_to(actor, session)
        .filter(pk=initial.assessment.exam_subject_id)
        .exists()
    ):
        raise PermissionDenied
    sheet = (
        MarkSheet.objects.select_for_update()
        .select_related("assessment__exam_subject")
        .get(pk=sheet_id)
    )
    if session.state != "open" or sheet.state not in ("draft", "returned"):
        raise ValidationError("Marks entry is closed or this sheet is already submitted/approved.")
    if sheet.version != expected_version:
        raise ValidationError(
            "Another user saved this marks sheet. Reload and review their changes."
        )
    candidates = {
        str(c.pk): c for c in session.candidates.filter(cohort=sheet.assessment.exam_subject.cohort)
    }
    if set(rows) != set(candidates):
        raise ValidationError(
            "Submit the exact eligible roster once. Reload if the roster changed."
        )
    existing = {str(e.candidate_id): e for e in sheet.entries.all()}
    create, update = [], []
    for key, data in rows.items():
        candidate = candidates[key]
        status, remarks = data.get("status", "pending"), data.get("remarks", "").strip()
        if status == "withheld" and not can_oversee(actor, session):
            raise PermissionDenied
        value = validate_mark(sheet.assessment, status, data.get("marks"), remarks)
        entry = existing.get(key)
        if entry:
            entry.status, entry.marks, entry.remarks, entry.changed_by = (
                status,
                value,
                remarks,
                actor,
            )
            entry.version += 1
            update.append(entry)
        else:
            create.append(
                MarkEntry(
                    sheet=sheet,
                    candidate=candidate,
                    status=status,
                    marks=value,
                    remarks=remarks,
                    changed_by=actor,
                )
            )
    MarkEntry.objects.bulk_create(create)
    MarkEntry.objects.bulk_update(update, ["status", "marks", "remarks", "changed_by", "version"])
    sheet.version += 1
    if submit:
        # Pending/incomplete are explicit statuses, never fabricated zeros.
        sheet.state, sheet.submitted_by, sheet.submitted_at = "submitted", actor, timezone.now()
        sheet.reviewed_by = sheet.reviewed_at = None
        sheet.review_reason = ""
    sheet.save()
    event(
        actor,
        session,
        "marks_submitted" if submit else "marks_saved",
        "Complete roster submitted" if submit else "Draft saved",
        sheet=sheet,
    )
    return sheet


@transaction.atomic
def review_sheet(actor, sheet_id, decision, *, expected_version, reason):
    initial = MarkSheet.objects.select_related("assessment__exam_subject__cohort").get(pk=sheet_id)
    session = lock_session(initial.assessment.exam_subject.cohort.session_id)
    require(actor, "review_results", session)
    sheet = MarkSheet.objects.select_for_update().get(pk=sheet_id)
    if sheet.version != expected_version or session.state not in ("open", "closed"):
        raise ValidationError("The sheet or session changed; reload before reviewing.")
    if not reason.strip() or decision not in ("review", "return", "approve"):
        raise ValidationError("Choose a review decision and give a reason.")
    if sheet.state not in ("submitted", "review"):
        raise ValidationError("Only a submitted sheet can be reviewed.")
    if session.policy.independent_review and sheet.submitted_by_id == actor.pk:
        raise ValidationError("You cannot review your own submission under this policy.")
    sheet.state = {"review": "review", "return": "returned", "approve": "approved"}[decision]
    sheet.reviewed_by, sheet.reviewed_at, sheet.review_reason = actor, timezone.now(), reason
    sheet.version += 1
    sheet.save()
    event(actor, session, f"sheet_{decision}", reason, sheet=sheet)
    return sheet


def image_snapshot(field):
    if not field:
        return None
    try:
        with field.open("rb") as file:
            data = file.read(2 * 1024 * 1024 + 1)
        return base64.b64encode(data).decode("ascii") if len(data) <= 2 * 1024 * 1024 else None
    except OSError:
        return None


def make_publication(actor, session, reason):
    version = (session.publications.aggregate(last=Max("version"))["last"] or 0) + 1
    settings = ExaminationSettings.objects.first() or ExaminationSettings()
    ranking = {
        key: getattr(settings, key)
        for key in ("ranking_enabled", "ranking_scope", "ranking_ties", "ranking_pass_only")
    }
    publication = ResultPublication.objects.create(
        session=session, version=version, issued_by=actor, reason=reason, ranking_policy=ranking
    )
    school = SchoolSettings.objects.first()
    branding = {
        key: getattr(school, key, "")
        for key in ("name", "address", "phone", "email", "principal_name", "timezone")
    }
    branding["name"] = branding["name"] or "RumiWare SchoolOS"
    branding["logo"] = image_snapshot(school.logo) if school else None
    policy_data = {
        key: getattr(session.policy, key)
        for key in (
            "name",
            "absence_rule",
            "exemption_rule",
            "optional_rule",
            "decimal_places",
            "require_subject_pass",
            "independent_review",
            "principal_approval",
        )
    }
    policy_data["overall_pass"] = str(session.policy.overall_pass)
    policy_data["bands"] = [
        {
            "lower": str(b.lower),
            "upper": str(b.upper),
            "label": b.label,
            "description": b.description,
            "points": str(b.points) if b.points is not None else None,
        }
        for b in session.policy.bands.all()
    ]
    candidates = list(
        session.candidates.select_related(
            "student", "enrollment", "session__policy", "cohort__section__school_class"
        ).prefetch_related("marks__sheet__assessment")
    )
    bands = validate_policy(session.policy)
    contributions = list(session.contributions.select_related("source"))
    source_data = {}
    if session.report_kind != "assessment":
        for contribution in contributions:
            latest = contribution.source.publications.first()
            source_data[str(contribution.source_id)] = {
                str(r.candidate.student_id): {**r.data, "publication_id": str(latest.pk)}
                for r in latest.results.select_related("candidate")
            }
    subjects = {
        cohort.pk: list(
            cohort.subjects.select_related("subject").prefetch_related(
                "assessments__assessment_type"
            )
        )
        for cohort in session.cohorts.all()
    }
    snapshots = []
    for candidate in candidates:
        if session.report_kind == "assessment":
            result = calculate_candidate(
                candidate,
                subjects=subjects[candidate.cohort_id],
                entries=list(candidate.marks.all()),
                policy=session.policy,
                bands=bands,
            )
        else:
            result = aggregate_candidate(
                candidate,
                {key: data.get(str(candidate.student_id)) for key, data in source_data.items()},
                subjects=subjects[candidate.cohort_id],
                contributions=contributions,
                policy=session.policy,
                bands=bands,
            )
        result.update(
            {
                "school": branding,
                "policy": policy_data,
                "student": str(candidate.student),
                "student_id": str(candidate.student_id),
                "admission": candidate.student.admission_number,
                "photo": image_snapshot(candidate.student.photo),
                "roll": candidate.enrollment.roll_number,
                "class": candidate.cohort.section.school_class.name,
                "class_id": candidate.cohort.section.school_class_id,
                "section": candidate.cohort.section.name,
                "section_id": candidate.cohort.section_id,
                "year": session.academic_year.name,
                "session": session.name,
                "term": str(session.term.name) if session.term_id else "",
                "report_kind": session.report_kind,
                "teacher_remarks": candidate.teacher_remarks
                if result["outcome"] != "withheld"
                else "",
                "principal_remarks": candidate.principal_remarks
                if result["outcome"] != "withheld"
                else "",
                "approved_by": session.approved_by.display_name if session.approved_by_id else "",
                "approved_at": session.approved_at.isoformat() if session.approved_at else None,
                "issued_at": school_now().isoformat(),
                "issued_by": actor.display_name,
                "version": version,
                "publication_id": str(publication.pk),
                "rank": None,
            }
        )
        snapshots.append(PublishedResult(publication=publication, candidate=candidate, data=result))
    if settings.ranking_enabled:
        apply_rankings(snapshots, settings)
    PublishedResult.objects.bulk_create(snapshots)
    return publication


def apply_rankings(snapshots, settings):
    groups = {}
    for row in snapshots:
        data = row.data
        if data["outcome"] not in ("pass", "fail") or (
            settings.ranking_pass_only and data["outcome"] != "pass"
        ):
            continue
        key = data["section_id"] if settings.ranking_scope == "section" else data["class_id"]
        groups.setdefault(key, []).append(data)
    for values in groups.values():
        values.sort(key=lambda d: Decimal(d["raw_percentage"]), reverse=True)
        previous, rank, dense = None, 0, 0
        for index, data in enumerate(values, start=1):
            value = Decimal(data["raw_percentage"])
            if value != previous:
                dense += 1
                rank = dense if settings.ranking_ties == "dense" else index
            data["rank"] = rank
            previous = value


@transaction.atomic
def update_candidate(
    actor,
    candidate_id,
    *,
    teacher_remarks,
    principal_remarks,
    withheld,
    withholding_reason,
    expected_version,
):
    initial = ExamCandidate.objects.get(pk=candidate_id)
    session = lock_session(initial.session_id)
    require(actor, "review_results", session)
    if session.version != expected_version or session.state not in ("open", "closed", "review"):
        raise ValidationError(
            "Remarks and withholding are frozen at approval. Reload the session if it changed."
        )
    if principal_remarks != initial.principal_remarks and not capable(actor, "approve_results"):
        raise PermissionDenied
    initial.teacher_remarks, initial.principal_remarks = teacher_remarks, principal_remarks
    initial.withheld, initial.withholding_reason = (
        withheld,
        withholding_reason.strip() if withheld else "",
    )
    initial.full_clean()
    initial.save()
    session.version += 1
    session.save()
    event(actor, session, "remarks_saved", "Candidate remarks or withholding updated")
    return initial


def entry_values(entry):
    return {
        "status": entry.status,
        "marks": str(entry.marks) if entry.marks is not None else None,
        "remarks": entry.remarks,
        "version": entry.version,
    }


@transaction.atomic
def request_correction(actor, entry_id, *, status, marks, remarks, reason):
    entry = MarkEntry.objects.select_related("sheet__assessment__exam_subject__cohort").get(
        pk=entry_id
    )
    session = lock_session(entry.sheet.assessment.exam_subject.cohort.session_id)
    if (
        not capable(actor, "correct_results")
        or not sheets_visible_to(actor).filter(pk=entry.sheet_id).exists()
    ):
        raise PermissionDenied
    if session.state == "archived" or entry.sheet.state != "approved":
        raise ValidationError(
            "Request corrections for approved marks in an open academic year before archival."
        )
    if status == "withheld" and not can_oversee(actor, session):
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError("Give the reason for this correction.")
    value = validate_mark(entry.sheet.assessment, status, marks, remarks)
    after = {
        "status": status,
        "marks": str(value) if value is not None else None,
        "remarks": remarks,
        "version": entry.version + 1,
    }
    before = entry_values(entry)
    if all(before[k] == after[k] for k in ("status", "marks", "remarks")):
        raise ValidationError("The proposed correction makes no change.")
    correction = ResultCorrection(
        entry=entry, before=before, after=after, reason=reason, requested_by=actor
    )
    correction.full_clean()
    correction.save()
    event(
        actor,
        session,
        "correction_requested",
        "Mark correction awaiting independent review",
        sheet=entry.sheet,
    )
    return correction


@transaction.atomic
def decide_correction(actor, correction_id, *, approve, reason):
    initial = ResultCorrection.objects.select_related(
        "entry__sheet__assessment__exam_subject__cohort"
    ).get(pk=correction_id)
    session = lock_session(initial.entry.sheet.assessment.exam_subject.cohort.session_id)
    require(actor, "decide_corrections", session)
    correction = (
        ResultCorrection.objects.select_for_update().select_related("entry").get(pk=correction_id)
    )
    if (
        correction.state != "pending"
        or correction.requested_by_id == actor.pk
        or not reason.strip()
    ):
        raise ValidationError(
            "An independent reviewer must decide a pending request and provide a reason."
        )
    if session.state == "archived":
        raise ValidationError("Archived sessions are protected.")
    if entry_values(correction.entry) != correction.before:
        raise ValidationError(
            "The original marks changed. Request a new correction after reviewing them."
        )
    correction.state = "approved" if approve else "rejected"
    correction.reviewed_by, correction.reviewed_at, correction.decision_reason = (
        actor,
        timezone.now(),
        reason,
    )
    correction.full_clean()
    correction.save()
    if approve:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('schoolos.result_correction', %s, true)", [str(correction.pk)]
            )
        entry = correction.entry
        entry.status, entry.marks, entry.remarks = (
            correction.after["status"],
            correction.after["marks"],
            correction.after["remarks"],
        )
        entry.version, entry.changed_by = correction.after["version"], actor
        entry.full_clean()
        entry.save()
        if session.state == "published":
            make_publication(actor, session, f"Approved correction {correction.pk}: {reason}")
    event(
        actor,
        session,
        "correction_approved" if approve else "correction_rejected",
        reason,
        sheet=initial.entry.sheet,
        public=approve and session.state == "published",
    )
    return correction


@transaction.atomic
def override_recommendation(actor, candidate_id, *, eligible, reason):
    candidate = ExamCandidate.objects.select_related("session").get(pk=candidate_id)
    session = lock_session(candidate.session_id)
    require(actor, "override_promotion", session)
    latest = session.publications.first()
    if not latest or not reason.strip():
        raise ValidationError(
            "Publish results first and give a reason for the recommendation override."
        )
    row = PromotionRecommendation.objects.create(
        candidate=candidate, publication=latest, eligible=eligible, reason=reason, actor=actor
    )
    event(actor, session, "promotion_override", reason)
    return row


def candidate_values(candidate):
    return {
        key: getattr(candidate, key)
        for key in ("teacher_remarks", "principal_remarks", "withheld", "withholding_reason")
    }


@transaction.atomic
def request_amendment(
    actor,
    candidate_id,
    *,
    teacher_remarks,
    principal_remarks,
    withheld,
    withholding_reason,
    expected_version,
    reason,
):
    candidate = ExamCandidate.objects.select_related("session").get(pk=candidate_id)
    session = lock_session(candidate.session_id)
    require(actor, "correct_results", session)
    if session.state not in ("approved", "published") or session.version != expected_version:
        raise ValidationError(
            "Request an amendment after approval, before archival, "
            "using the current session version."
        )
    if not reason.strip():
        raise ValidationError("Explain the requested amendment.")
    if principal_remarks != candidate.principal_remarks and not capable(actor, "approve_results"):
        raise PermissionDenied
    before = candidate_values(candidate)
    after = {
        "teacher_remarks": teacher_remarks,
        "principal_remarks": principal_remarks,
        "withheld": withheld,
        "withholding_reason": withholding_reason.strip() if withheld else "",
    }
    if before == after:
        raise ValidationError("The proposed amendment makes no change.")
    for key, value in after.items():
        setattr(candidate, key, value)
    candidate.full_clean()
    row = CandidateAmendment(
        candidate=candidate, before=before, after=after, reason=reason, requested_by=actor
    )
    row.full_clean()
    row.save()
    event(actor, session, "amendment_requested", "Candidate amendment awaiting independent review")
    return row


@transaction.atomic
def decide_amendment(actor, amendment_id, *, approve, reason):
    row = CandidateAmendment.objects.select_related("candidate").get(pk=amendment_id)
    session = lock_session(row.candidate.session_id)
    require(actor, "decide_corrections", session)
    row = (
        CandidateAmendment.objects.select_for_update()
        .select_related("candidate")
        .get(pk=amendment_id)
    )
    if row.state != "pending" or row.requested_by_id == actor.pk or not reason.strip():
        raise ValidationError("An independent reviewer and decision reason are required.")
    if (
        session.state not in ("approved", "published")
        or candidate_values(row.candidate) != row.before
    ):
        raise ValidationError(
            "The result changed or was archived; review the current record before requesting again."
        )
    if row.after["principal_remarks"] != row.before["principal_remarks"] and not capable(
        actor, "approve_results"
    ):
        raise PermissionDenied
    row.state = "approved" if approve else "rejected"
    row.reviewed_by, row.reviewed_at, row.decision_reason = actor, timezone.now(), reason
    row.full_clean()
    row.save()
    if approve:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('schoolos.result_amendment', %s, true)", [str(row.pk)]
            )
        for key, value in row.after.items():
            setattr(row.candidate, key, value)
        row.candidate.full_clean()
        row.candidate.save()
        if session.state == "published":
            make_publication(actor, session, f"Approved amendment {row.pk}: {reason}")
    event(
        actor,
        session,
        "amendment_approved" if approve else "amendment_rejected",
        reason,
        public=approve and session.state == "published",
    )
    return row
