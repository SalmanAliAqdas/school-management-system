"""Decimal-only grading. Missing information never acquires an invented mark."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

D = Decimal
HUNDRED = D("100")


def number(value):
    return D(str(value))


def formatted(value, policy):
    if value is None:
        return None
    return str(value.quantize(D(1).scaleb(-policy.decimal_places), rounding=ROUND_HALF_UP))


def validate_policy(policy):
    bands = list(policy.bands.order_by("lower"))
    cursor = D(0)
    for band in bands:
        if band.lower != cursor or band.upper <= band.lower:
            raise ValidationError(
                "Grade bands must cover 0–100 contiguously without gaps or overlaps."
            )
        cursor = band.upper
    if not bands or cursor != HUNDRED:
        raise ValidationError("Grade bands must begin at 0 and end at 100.")
    return bands


def grade_for(value, policy, bands=None):
    if value is None:
        return None, None
    for band in bands if bands is not None else validate_policy(policy):
        if band.lower <= value < band.upper or value == HUNDRED == band.upper:
            return band.label, str(band.points) if band.points is not None else None
    raise ValidationError("This percentage is outside the configured grading scale.")


def validate_weights(items, label):
    items = list(items)
    if not items or sum((item.weight for item in items), D(0)) != HUNDRED:
        raise ValidationError(
            f"{label} weights must total exactly 100%. Configure every weight explicitly."
        )
    return items


def subject_result(subject, entries, policy, bands):
    assessments = list(subject.assessments.all())
    validate_weights(assessments, str(subject.subject))
    weighted = D(0)
    denominator = D(0)
    obtained = D(0)
    maximum = D(0)
    incomplete = False
    component_failure = False
    components = []
    for assessment in assessments:
        entry = entries.get(str(assessment.pk))
        status = entry.status if entry else "pending"
        mark = entry.marks if entry else None
        row = {
            "assessment": assessment.name,
            "assessment_id": str(assessment.pk),
            "component": assessment.component,
            "type": assessment.assessment_type.name,
            "status": status,
            "marks": str(mark) if mark is not None else None,
            "maximum": str(assessment.max_marks),
            "weight": str(assessment.weight),
            "remarks": entry.remarks if entry else "",
        }
        components.append(row)
        excluded = status == "exempt" and policy.exemption_rule == "exclude"
        excluded |= (
            assessment.optional and status == "pending" and policy.optional_rule == "exclude"
        )
        if excluded:
            row["excluded"] = True
            continue
        if status == "absent" and policy.absence_rule == "zero":
            mark = D(0)
            row["absence_credit"] = "Explicit zero credit under published policy"
        elif status != "assessed":
            incomplete = True
            continue
        if mark is None:
            incomplete = True
            continue
        credit = mark / assessment.max_marks * HUNDRED
        weighted += credit * assessment.weight
        denominator += assessment.weight
        obtained += mark
        maximum += assessment.max_marks
        if assessment.require_pass and credit < assessment.passing_percentage:
            component_failure = True
    raw = weighted / denominator if denominator and not incomplete else None
    state = (
        "incomplete"
        if incomplete
        else "exempt"
        if not denominator
        else ("pass" if raw >= subject.passing_percentage and not component_failure else "fail")
    )
    grade, points = grade_for(raw, policy, bands)
    return {
        "subject_id": subject.subject_id,
        "subject": subject.subject.name,
        "weight": str(subject.weight),
        "required": subject.required,
        "passing_percentage": str(subject.passing_percentage),
        "components": components,
        "outcome": state,
        "percentage": formatted(raw, policy),
        "raw_percentage": str(raw) if raw is not None else None,
        "obtained": str(obtained) if not incomplete and denominator else None,
        "maximum": str(maximum) if not incomplete and denominator else None,
        "grade": grade,
        "points": points,
    }


def overall_result(subjects, policy, bands):
    included = [row for row in subjects if row["outcome"] != "exempt"]
    incomplete = not included or any(row["raw_percentage"] is None for row in included)
    weighted = sum(
        (
            number(row["raw_percentage"]) * number(row["weight"])
            for row in included
            if row["raw_percentage"] is not None
        ),
        D(0),
    )
    denominator = sum((number(row["weight"]) for row in included), D(0))
    raw = weighted / denominator if denominator and not incomplete else None
    failed = any(row["outcome"] == "fail" and row["required"] for row in included)
    state = (
        "incomplete"
        if incomplete
        else "pass"
        if raw >= policy.overall_pass and (not policy.require_subject_pass or not failed)
        else "fail"
    )
    grade, points = grade_for(raw, policy, bands)
    return {
        "subjects": subjects,
        "percentage": formatted(raw, policy),
        "raw_percentage": str(raw) if raw is not None else None,
        "obtained": str(sum((number(row["obtained"]) for row in included), D(0)))
        if not incomplete
        else None,
        "maximum": str(sum((number(row["maximum"]) for row in included), D(0)))
        if not incomplete
        else None,
        "grade": grade,
        "points": points,
        "outcome": state,
        "promotion": "eligible" if state == "pass" and not failed else "academic_review",
    }


def calculate_candidate(candidate, *, subjects=None, entries=None, policy=None, bands=None):
    policy = policy or candidate.session.policy
    bands = validate_policy(policy) if bands is None else bands
    if entries is None:
        entries = list(candidate.marks.select_related("sheet__assessment"))
    if candidate.withheld or any(entry.status == "withheld" for entry in entries):
        return {
            "outcome": "withheld",
            "subjects": [],
            "percentage": None,
            "raw_percentage": None,
            "obtained": None,
            "maximum": None,
            "grade": None,
            "points": None,
            "promotion": "academic_review",
        }
    subjects = (
        subjects
        if subjects is not None
        else candidate.cohort.subjects.select_related("subject").prefetch_related(
            "assessments__assessment_type"
        )
    )
    subjects = validate_weights(subjects, "Subject")
    by_assessment = {str(entry.sheet.assessment_id): entry for entry in entries}
    return overall_result(
        [subject_result(subject, by_assessment, policy, bands) for subject in subjects],
        policy,
        bands,
    )


def aggregate_candidate(
    candidate, sources, *, subjects=None, contributions=None, policy=None, bands=None
):
    """Sources are exact publication snapshots, never current mutable marks."""
    policy = policy or candidate.session.policy
    bands = validate_policy(policy) if bands is None else bands
    contributions = validate_weights(
        contributions
        if contributions is not None
        else candidate.session.contributions.select_related("source"),
        "Source session",
    )
    if candidate.withheld or any(
        data and data.get("outcome") == "withheld" for data in sources.values()
    ):
        return {
            "outcome": "withheld",
            "subjects": [],
            "percentage": None,
            "raw_percentage": None,
            "obtained": None,
            "maximum": None,
            "grade": None,
            "points": None,
            "promotion": "academic_review",
        }
    rows = []
    subjects = validate_weights(
        subjects if subjects is not None else candidate.cohort.subjects.select_related("subject"),
        "Subject",
    )
    for subject in subjects:
        components = []
        weighted = denominator = D(0)
        incomplete = False
        for contribution in contributions:
            data = sources.get(str(contribution.source_id))
            source_subject = next(
                (
                    row
                    for row in (data or {}).get("subjects", [])
                    if row["subject_id"] == subject.subject_id
                ),
                None,
            )
            component = {
                "assessment": contribution.source.name,
                "weight": str(contribution.weight),
                "source_session": str(contribution.source_id),
                "publication": (data or {}).get("publication_id"),
                "status": source_subject["outcome"] if source_subject else "pending",
                "marks": source_subject.get("percentage") if source_subject else None,
                "maximum": "100",
            }
            components.append(component)
            if (
                source_subject
                and source_subject["outcome"] == "exempt"
                and policy.exemption_rule == "exclude"
            ):
                component["excluded"] = True
                continue
            if not source_subject or source_subject.get("raw_percentage") is None:
                incomplete = True
                continue
            weighted += number(source_subject["raw_percentage"]) * contribution.weight
            denominator += contribution.weight
        raw = weighted / denominator if denominator and not incomplete else None
        outcome = (
            "incomplete"
            if incomplete
            else "exempt"
            if not denominator
            else ("pass" if raw >= subject.passing_percentage else "fail")
        )
        grade, points = grade_for(raw, policy, bands)
        rows.append(
            {
                "subject_id": subject.subject_id,
                "subject": subject.subject.name,
                "weight": str(subject.weight),
                "required": subject.required,
                "passing_percentage": str(subject.passing_percentage),
                "components": components,
                "outcome": outcome,
                "raw_percentage": str(raw) if raw is not None else None,
                "percentage": formatted(raw, policy),
                "grade": grade,
                "points": points,
                "obtained": str(raw) if raw is not None else None,
                "maximum": "100" if raw is not None else None,
            }
        )
    return overall_result(rows, policy, bands)
