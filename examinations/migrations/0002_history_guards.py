from django.db import migrations

SQL = r"""
CREATE FUNCTION schoolos_exam_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Issued examination history is append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION schoolos_exam_session_guard() RETURNS trigger AS $$
DECLARE yr academics_academicyear%ROWTYPE; pol examinations_gradingpolicy%ROWTYPE;
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Examination sessions are retained' USING ERRCODE='23514';
    END IF;
    SELECT * INTO yr FROM academics_academicyear WHERE id=NEW.academic_year_id FOR UPDATE;
    SELECT * INTO pol FROM examinations_gradingpolicy WHERE id=NEW.policy_id;
    IF NEW.starts_on<yr.starts_on OR NEW.ends_on>yr.ends_on OR pol.academic_year_id<>yr.id
       OR (NEW.term_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM academics_term t WHERE t.id=NEW.term_id
           AND t.academic_year_id=yr.id AND NEW.starts_on>=t.starts_on AND NEW.ends_on<=t.ends_on)) THEN
        RAISE EXCEPTION 'Examination dates and policy must match the academic period' USING ERRCODE='23514';
    END IF;
    IF TG_OP='INSERT' AND (NEW.state<>'draft' OR yr.status<>'open') THEN
        RAISE EXCEPTION 'Create examination setup as a draft in an open year' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' THEN
        IF NEW.academic_year_id<>OLD.academic_year_id OR NEW.created_by_id<>OLD.created_by_id THEN
            RAISE EXCEPTION 'Examination identity is immutable' USING ERRCODE='23514';
        END IF;
        IF OLD.state<>'draft' AND (to_jsonb(NEW)-ARRAY['state','version','approved_at','approved_by_id','updated_at'])
            IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','approved_at','approved_by_id','updated_at']) THEN
            RAISE EXCEPTION 'Used examination configuration is immutable' USING ERRCODE='23514';
        END IF;
        IF (yr.status<>'open' AND NOT (OLD.state='published' AND NEW.state='archived')) OR OLD.state='archived'
          OR (OLD.state='approved' AND NEW.state NOT IN ('approved','published'))
          OR (OLD.state='published' AND NEW.state NOT IN ('published','archived')) THEN
            RAISE EXCEPTION 'Approved or closed examination history is protected' USING ERRCODE='23514';
        END IF;
        IF NEW.state<>OLD.state AND NOT (
            (OLD.state='draft' AND NEW.state='open') OR (OLD.state='open' AND NEW.state='closed') OR
            (OLD.state='closed' AND NEW.state IN ('open','review')) OR (OLD.state='review' AND NEW.state IN ('open','approved')) OR
            (OLD.state='approved' AND NEW.state='published') OR (OLD.state='published' AND NEW.state='archived')) THEN
            RAISE EXCEPTION 'Invalid examination transition' USING ERRCODE='23514';
        END IF;
        IF OLD.state='draft' AND NEW.state='open' THEN
            IF NOT EXISTS (SELECT 1 FROM examinations_examcandidate WHERE session_id=NEW.id)
               OR EXISTS (SELECT 1 FROM examinations_examcohort c WHERE c.session_id=NEW.id AND
                   (SELECT COALESCE(sum(s.weight),0) FROM examinations_examsubject s WHERE s.cohort_id=c.id)<>100)
               OR (NEW.report_kind='assessment' AND EXISTS (SELECT 1 FROM examinations_examsubject s
                   JOIN examinations_examcohort c ON c.id=s.cohort_id WHERE c.session_id=NEW.id AND
                   (SELECT COALESCE(sum(a.weight),0) FROM examinations_assessment a WHERE a.exam_subject_id=s.id)<>100))
               OR (NEW.report_kind<>'assessment' AND (SELECT COALESCE(sum(weight),0)
                   FROM examinations_sessioncontribution WHERE session_id=NEW.id)<>100) THEN
                RAISE EXCEPTION 'Complete weights and a valid frozen roster are required' USING ERRCODE='23514';
            END IF;
        END IF;
        IF NEW.state IN ('review','approved') AND NEW.report_kind='assessment' AND EXISTS
            (SELECT 1 FROM examinations_marksheet m JOIN examinations_assessment a ON a.id=m.assessment_id
             JOIN examinations_examsubject s ON s.id=a.exam_subject_id JOIN examinations_examcohort c ON c.id=s.cohort_id
             WHERE c.session_id=NEW.id AND (m.state<>'approved' OR
                (NEW.state='approved' AND pol.independent_review AND m.submitted_by_id=NEW.approved_by_id))) THEN
            RAISE EXCEPTION 'Independent marks approval is required' USING ERRCODE='23514';
        END IF;
        IF NEW.state='published' AND OLD.state<>'published' AND NOT EXISTS
            (SELECT 1 FROM examinations_resultpublication WHERE session_id=NEW.id) THEN
            RAISE EXCEPTION 'Publication snapshots are required' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_session_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examsession
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_session_guard();

CREATE FUNCTION schoolos_exam_setup_guard() RETURNS trigger AS $$
DECLARE obj jsonb; session_id uuid; state_value text; year_id bigint;
BEGIN
    obj=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF TG_TABLE_NAME IN ('examinations_examcohort','examinations_examcontroller','examinations_sessioncontribution') THEN
        session_id=(obj->>'session_id')::uuid;
    ELSIF TG_TABLE_NAME='examinations_examsubject' THEN
        SELECT c.session_id INTO session_id FROM examinations_examcohort c WHERE c.id=(obj->>'cohort_id')::bigint;
    ELSE
        SELECT c.session_id INTO session_id FROM examinations_examsubject s JOIN examinations_examcohort c ON c.id=s.cohort_id
          WHERE s.id=(obj->>'exam_subject_id')::bigint;
    END IF;
    SELECT e.academic_year_id INTO year_id FROM examinations_examsession e WHERE e.id=session_id;
    PERFORM 1 FROM academics_academicyear WHERE id=year_id FOR UPDATE;
    SELECT e.state INTO state_value FROM examinations_examsession e WHERE e.id=session_id;
    IF state_value<>'draft' THEN
        RAISE EXCEPTION 'Used examination setup is immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' AND (to_jsonb(OLD)->>'session_id' IS DISTINCT FROM obj->>'session_id'
       OR to_jsonb(OLD)->>'cohort_id' IS DISTINCT FROM obj->>'cohort_id'
       OR to_jsonb(OLD)->>'exam_subject_id' IS DISTINCT FROM obj->>'exam_subject_id') THEN
        RAISE EXCEPTION 'Examination setup cannot be moved' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_cohort_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examcohort
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_setup_guard();
CREATE TRIGGER exam_subject_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examsubject
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_setup_guard();
CREATE TRIGGER exam_assessment_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_assessment
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_setup_guard();
CREATE TRIGGER exam_controller_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examcontroller
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_setup_guard();
CREATE TRIGGER exam_contribution_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_sessioncontribution
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_setup_guard();

CREATE FUNCTION schoolos_exam_policy_guard() RETURNS trigger AS $$
DECLARE chosen_policy uuid; obj jsonb; yr bigint;
BEGIN
    obj=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    chosen_policy=CASE WHEN TG_TABLE_NAME='examinations_gradingpolicy' THEN (obj->>'id')::uuid ELSE (obj->>'policy_id')::uuid END;
    IF TG_TABLE_NAME='examinations_gradingpolicy' THEN yr=(obj->>'academic_year_id')::bigint;
    ELSE SELECT academic_year_id INTO yr FROM examinations_gradingpolicy WHERE id=chosen_policy; END IF;
    PERFORM 1 FROM academics_academicyear WHERE id=yr FOR UPDATE;
    IF EXISTS (SELECT 1 FROM examinations_examsession WHERE examinations_examsession.policy_id=chosen_policy AND state<>'draft') THEN
        RAISE EXCEPTION 'Used grading policies and bands are immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' AND (obj->>'policy_id' IS DISTINCT FROM to_jsonb(OLD)->>'policy_id' OR
                           obj->>'academic_year_id' IS DISTINCT FROM to_jsonb(OLD)->>'academic_year_id') THEN
        RAISE EXCEPTION 'Policy identity is immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_policy_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_gradingpolicy
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_policy_guard();
CREATE TRIGGER exam_band_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_gradeband
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_policy_guard();

CREATE FUNCTION schoolos_exam_candidate_guard() RETURNS trigger AS $$
DECLARE e examinations_examsession%ROWTYPE; p people_enrollment%ROWTYPE; c examinations_examcohort%ROWTYPE;
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
    IF TG_OP='UPDATE' AND (e.state IN ('approved','published','archived') OR
        NEW.cohort_id<>OLD.cohort_id OR NEW.session_id<>OLD.session_id OR NEW.student_id<>OLD.student_id OR NEW.enrollment_id<>OLD.enrollment_id) THEN
        RAISE EXCEPTION 'Candidate identity and approved remarks are protected' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_candidate_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_examcandidate
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_candidate_guard();

CREATE FUNCTION schoolos_exam_sheet_guard() RETURNS trigger AS $$
DECLARE c bigint; e examinations_examsession%ROWTYPE; independent boolean;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Marks sheets are retained' USING ERRCODE='23514'; END IF;
    SELECT s.cohort_id INTO c FROM examinations_assessment a JOIN examinations_examsubject s ON s.id=a.exam_subject_id WHERE a.id=NEW.assessment_id;
    SELECT x.* INTO e FROM examinations_examsession x JOIN examinations_examcohort c1 ON c1.session_id=x.id WHERE c1.id=c;
    PERFORM 1 FROM academics_academicyear WHERE id=e.academic_year_id FOR UPDATE;
    SELECT independent_review INTO independent FROM examinations_gradingpolicy WHERE id=e.policy_id;
    IF TG_OP='UPDATE' AND (OLD.state='approved' OR NEW.assessment_id<>OLD.assessment_id OR e.state NOT IN ('open','closed')) THEN
        RAISE EXCEPTION 'Approved marks sheets are protected' USING ERRCODE='23514';
    END IF;
    IF TG_OP='INSERT' AND (e.state<>'draft' OR NEW.state<>'draft') THEN
        RAISE EXCEPTION 'Create marks sheets while opening draft setup' USING ERRCODE='23514';
    END IF;
    IF NEW.state IN ('submitted','review','approved') AND (
        NEW.submitted_by_id IS NULL OR NEW.submitted_at IS NULL OR
        (SELECT count(*) FROM examinations_markentry WHERE sheet_id=NEW.id)<>(SELECT count(*) FROM examinations_examcandidate WHERE cohort_id=c)) THEN
        RAISE EXCEPTION 'Submission requires the complete eligible roster' USING ERRCODE='23514';
    END IF;
    IF NEW.state IN ('review','returned','approved') AND (NEW.reviewed_by_id IS NULL OR NEW.reviewed_at IS NULL OR
        NEW.review_reason='' OR (independent AND NEW.submitted_by_id=NEW.reviewed_by_id)) THEN
        RAISE EXCEPTION 'An independent review and reason are required' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_sheet_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_marksheet
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_sheet_guard();

CREATE FUNCTION schoolos_exam_mark_guard() RETURNS trigger AS $$
DECLARE a examinations_assessment%ROWTYPE; m examinations_marksheet%ROWTYPE; c examinations_examcandidate%ROWTYPE;
DECLARE sess examinations_examsession%ROWTYPE; subcohort bigint; token text; correction examinations_resultcorrection%ROWTYPE;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Marks history is retained' USING ERRCODE='23514'; END IF;
    SELECT * INTO m FROM examinations_marksheet WHERE id=NEW.sheet_id;
    SELECT * INTO a FROM examinations_assessment WHERE id=m.assessment_id;
    SELECT cohort_id INTO subcohort FROM examinations_examsubject WHERE id=a.exam_subject_id;
    SELECT * INTO c FROM examinations_examcandidate WHERE id=NEW.candidate_id;
    SELECT * INTO sess FROM examinations_examsession WHERE id=c.session_id;
    PERFORM 1 FROM academics_academicyear WHERE id=sess.academic_year_id FOR UPDATE;
    IF c.cohort_id<>subcohort OR NEW.marks>a.max_marks THEN
        RAISE EXCEPTION 'Marks must match the assessment maximum and eligible roster' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' AND (NEW.sheet_id<>OLD.sheet_id OR NEW.candidate_id<>OLD.candidate_id) THEN
        RAISE EXCEPTION 'Mark identity is immutable' USING ERRCODE='23514';
    END IF;
    IF m.state NOT IN ('draft','returned') OR sess.state<>'open' THEN
        token=current_setting('schoolos.result_correction',true);
        IF TG_OP<>'UPDATE' OR m.state<>'approved' OR sess.state='archived' OR token IS NULL OR token='' THEN
            RAISE EXCEPTION 'Submitted marks require an approved correction' USING ERRCODE='23514';
        END IF;
        SELECT * INTO correction FROM examinations_resultcorrection WHERE id=token::uuid AND entry_id=OLD.id AND state='approved';
        IF NOT FOUND OR correction.before->>'status'<>OLD.status OR
           (correction.before->>'marks')::numeric IS DISTINCT FROM OLD.marks OR
           (correction.before->>'version')::integer<>OLD.version OR correction.before->>'remarks'<>OLD.remarks OR
           correction.after->>'status'<>NEW.status OR (correction.after->>'marks')::numeric IS DISTINCT FROM NEW.marks OR
           (correction.after->>'version')::integer<>NEW.version OR correction.after->>'remarks'<>NEW.remarks OR
           correction.reviewed_by_id<>NEW.changed_by_id THEN
            RAISE EXCEPTION 'Correction must match original and revised marks exactly' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_mark_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_markentry
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_mark_guard();

CREATE FUNCTION schoolos_exam_correction_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (OLD.state<>'pending' OR NEW.state NOT IN ('approved','rejected') OR
        (to_jsonb(OLD)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at']) IS DISTINCT FROM
        (to_jsonb(NEW)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at']))) THEN
        RAISE EXCEPTION 'Correction requests and completed decisions are immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='INSERT' AND NEW.state<>'pending' THEN
        RAISE EXCEPTION 'Request an independent correction review first' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_correction_guard BEFORE INSERT OR UPDATE OR DELETE ON examinations_resultcorrection
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_correction_guard();

CREATE FUNCTION schoolos_exam_source_enrollment_guard() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM examinations_examcandidate c JOIN examinations_examsession e ON e.id=c.session_id
        JOIN examinations_examcohort co ON co.id=c.cohort_id WHERE c.enrollment_id=OLD.id AND
        (TG_OP='DELETE' OR NEW.student_id<>c.student_id OR NEW.academic_year_id<>e.academic_year_id OR
         NEW.section_id<>co.section_id OR NEW.started_on>e.eligibility_on OR NEW.ended_on<e.eligibility_on)) THEN
        RAISE EXCEPTION 'Enrollment changes cannot invalidate examination eligibility history' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_source_enrollment_guard BEFORE UPDATE OR DELETE ON people_enrollment
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_source_enrollment_guard();

CREATE FUNCTION schoolos_exam_snapshot_guard() RETURNS trigger AS $$
DECLARE session_id uuid; expected_session uuid;
BEGIN
    IF TG_TABLE_NAME='examinations_publishedresult' THEN
        SELECT p.session_id INTO session_id FROM examinations_resultpublication p WHERE p.id=NEW.publication_id;
        SELECT c.session_id INTO expected_session FROM examinations_examcandidate c WHERE c.id=NEW.candidate_id;
        IF session_id<>expected_session THEN RAISE EXCEPTION 'Snapshot candidate must match publication' USING ERRCODE='23514'; END IF;
    ELSE
        session_id=NEW.session_id;
        IF NOT EXISTS (SELECT 1 FROM examinations_examsession e WHERE e.id=session_id AND e.state IN ('approved','published'))
           OR NEW.reason='' OR NEW.version<>(SELECT COALESCE(max(version),0)+1 FROM examinations_resultpublication WHERE examinations_resultpublication.session_id=NEW.session_id) THEN
            RAISE EXCEPTION 'Publish approved sessions with the next version and a reason' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exam_publication_insert_guard BEFORE INSERT ON examinations_resultpublication
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_snapshot_guard();
CREATE TRIGGER exam_snapshot_insert_guard BEFORE INSERT ON examinations_publishedresult
FOR EACH ROW EXECUTE FUNCTION schoolos_exam_snapshot_guard();
"""

IMMUTABLE_TABLES = (
    "resultpublication",
    "publishedresult",
    "resultevent",
    "promotionrecommendation",
)


def create_guards(apps, schema_editor):
    schema_editor.execute(SQL, params=None)
    for table in IMMUTABLE_TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER exam_{table}_immutable BEFORE UPDATE OR DELETE ON examinations_{table} "
            "FOR EACH ROW EXECUTE FUNCTION schoolos_exam_immutable()"
        )


def remove_guards(apps, schema_editor):
    for name in (
        "immutable",
        "session_guard",
        "setup_guard",
        "policy_guard",
        "candidate_guard",
        "sheet_guard",
        "mark_guard",
        "correction_guard",
        "source_enrollment_guard",
        "snapshot_guard",
    ):
        schema_editor.execute(f"DROP FUNCTION IF EXISTS schoolos_exam_{name}() CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("examinations", "0001_initial"),
        ("attendance", "0005_absencenotification_one_active_absence_notice"),
    ]
    operations = [migrations.RunPython(create_guards, remove_guards)]
