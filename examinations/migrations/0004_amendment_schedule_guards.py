from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION schoolos_exam_candidate_guard() RETURNS trigger AS $$
DECLARE e examinations_examsession%ROWTYPE; p people_enrollment%ROWTYPE; c examinations_examcohort%ROWTYPE;
DECLARE token text; amendment examinations_candidateamendment%ROWTYPE;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Candidate history is retained' USING ERRCODE='23514'; END IF;
    SELECT * INTO e FROM examinations_examsession WHERE id=NEW.session_id;
    PERFORM 1 FROM academics_academicyear WHERE id=e.academic_year_id FOR UPDATE;
    SELECT * INTO p FROM people_enrollment WHERE id=NEW.enrollment_id;
    SELECT * INTO c FROM examinations_examcohort WHERE id=NEW.cohort_id;
    IF p.student_id<>NEW.student_id OR c.session_id<>e.id OR p.academic_year_id<>e.academic_year_id
       OR p.section_id<>c.section_id OR p.started_on>e.eligibility_on OR p.ended_on<e.eligibility_on
       OR (TG_OP='INSERT' AND e.state<>'draft') THEN
        RAISE EXCEPTION 'Candidate must match the dated eligible enrollment' USING ERRCODE='23514';
    END IF;
    IF e.retake_of_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM examinations_examcandidate
         WHERE session_id=e.retake_of_id AND student_id=NEW.student_id) THEN
        RAISE EXCEPTION 'Retake candidates must belong to the original examination' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' THEN
        IF NEW.cohort_id<>OLD.cohort_id OR NEW.session_id<>OLD.session_id OR NEW.student_id<>OLD.student_id OR NEW.enrollment_id<>OLD.enrollment_id THEN
            RAISE EXCEPTION 'Candidate identity is immutable' USING ERRCODE='23514';
        END IF;
        IF e.state IN ('approved','published','archived') THEN
            token=current_setting('schoolos.result_amendment',true);
            IF e.state='archived' OR token IS NULL OR token='' THEN
                RAISE EXCEPTION 'Approved candidate remarks require independent amendment review' USING ERRCODE='23514';
            END IF;
            SELECT * INTO amendment FROM examinations_candidateamendment WHERE id=token::uuid AND candidate_id=OLD.id AND state='approved';
            IF NOT FOUND OR amendment.before IS DISTINCT FROM jsonb_build_object(
                'teacher_remarks',OLD.teacher_remarks,'principal_remarks',OLD.principal_remarks,
                'withheld',OLD.withheld,'withholding_reason',OLD.withholding_reason)
               OR amendment.after IS DISTINCT FROM jsonb_build_object(
                'teacher_remarks',NEW.teacher_remarks,'principal_remarks',NEW.principal_remarks,
                'withheld',NEW.withheld,'withholding_reason',NEW.withholding_reason) THEN
                RAISE EXCEPTION 'Amendment must match original and revised values' USING ERRCODE='23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_amendment_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_candidateamendment
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_correction_guard();

CREATE FUNCTION schoolos_exam_schedule_guard() RETURNS trigger AS $$
DECLARE obj jsonb; ses examinations_examsession%ROWTYPE; cohort examinations_examcohort%ROWTYPE;
DECLARE slot examinations_examschedule%ROWTYPE; yr bigint; class_id bigint; local_day date;
BEGIN
    obj=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF TG_TABLE_NAME='examinations_invigilation' THEN
        SELECT * INTO slot FROM examinations_examschedule WHERE id=(obj->>'schedule_id')::bigint;
    ELSE
        slot=CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END IF;
    SELECT c.* INTO cohort FROM examinations_assessment a JOIN examinations_examsubject s ON s.id=a.exam_subject_id
        JOIN examinations_examcohort c ON c.id=s.cohort_id WHERE a.id=slot.assessment_id;
    SELECT * INTO ses FROM examinations_examsession WHERE id=cohort.session_id;
    yr=ses.academic_year_id;
    PERFORM 1 FROM academics_academicyear WHERE id=yr FOR UPDATE;
    IF ses.state NOT IN ('draft','open') OR EXISTS (
        SELECT 1 FROM examinations_marksheet m JOIN examinations_assessment a ON a.id=m.assessment_id
        JOIN examinations_examsubject s ON s.id=a.exam_subject_id JOIN examinations_examcohort c ON c.id=s.cohort_id
        WHERE c.session_id=ses.id AND m.state<>'draft') THEN
        RAISE EXCEPTION 'Submitted examination schedules are protected' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    IF TG_TABLE_NAME='examinations_invigilation' THEN
        IF NEW.starts_at<>slot.starts_at OR NEW.ends_at<>slot.ends_at THEN
            RAISE EXCEPTION 'Invigilation must match the scheduled assessment times' USING ERRCODE='23514';
        END IF;
    ELSE
        SELECT school_class_id INTO class_id FROM academics_section WHERE id=cohort.section_id;
        local_day=(NEW.starts_at AT TIME ZONE COALESCE((SELECT timezone FROM core_schoolsettings LIMIT 1),'Asia/Karachi'))::date;
        IF NEW.section_id<>cohort.section_id OR NEW.school_class_id<>class_id OR local_day<ses.starts_on OR local_day>ses.ends_on OR
          local_day<>(NEW.ends_at AT TIME ZONE COALESCE((SELECT timezone FROM core_schoolsettings LIMIT 1),'Asia/Karachi'))::date THEN
            RAISE EXCEPTION 'Schedule must match its class and examination dates' USING ERRCODE='23514';
        END IF;
        IF TG_OP='UPDATE' AND EXISTS (SELECT 1 FROM examinations_invigilation WHERE schedule_id=OLD.id) THEN
            RAISE EXCEPTION 'Replace invigilation assignments before rescheduling' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_schedule_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examschedule
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_schedule_guard();
CREATE TRIGGER exam_invigilation_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_invigilation
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_schedule_guard();

CREATE FUNCTION schoolos_exam_approval_identity_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.state IN ('approved','published','archived') AND
       (NEW.approved_at IS DISTINCT FROM OLD.approved_at OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id) THEN
        RAISE EXCEPTION 'Recorded final approval is immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_approval_identity_guard BEFORE UPDATE ON examinations_examsession
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_approval_identity_guard();
"""


def install(apps, schema_editor):
    # Refresh the policy guard for databases upgraded during this phase as well as fresh installs.
    initial = import_module("examinations.migrations.0002_history_guards")
    policy = initial.SQL.split("CREATE FUNCTION schoolos_exam_policy_guard()", 1)[1].split(
        "CREATE TRIGGER exam_policy_guard", 1
    )[0]
    schema_editor.execute(
        "CREATE OR REPLACE FUNCTION schoolos_exam_policy_guard()" + policy, params=None
    )
    schema_editor.execute(SQL, params=None)


def uninstall(apps, schema_editor):
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS exam_amendment_guard ON examinations_candidateamendment"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS schoolos_exam_schedule_guard() CASCADE")
    schema_editor.execute("DROP FUNCTION IF EXISTS schoolos_exam_approval_identity_guard() CASCADE")
    initial = import_module("examinations.migrations.0002_history_guards")
    candidate = initial.SQL.split("CREATE FUNCTION schoolos_exam_candidate_guard()", 1)[1].split(
        "CREATE TRIGGER exam_candidate_guard", 1
    )[0]
    schema_editor.execute(
        "CREATE OR REPLACE FUNCTION schoolos_exam_candidate_guard()" + candidate, params=None
    )


class Migration(migrations.Migration):
    dependencies = [("examinations", "0003_candidateamendment_examsession_retake_of_and_more")]
    operations = [migrations.RunPython(install, uninstall)]
