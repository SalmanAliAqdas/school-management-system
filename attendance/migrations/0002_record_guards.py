from django.db import migrations

SQL = r"""
CREATE FUNCTION schoolos_attendance_register_guard() RETURNS trigger AS $$
DECLARE expected_count integer; actual_count integer; empty_count integer;
DECLARE period academics_academicyear%ROWTYPE; policy attendance_attendancepolicy%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Attendance registers cannot be deleted' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO period FROM academics_academicyear WHERE id=NEW.academic_year_id FOR UPDATE;
    SELECT * INTO policy FROM attendance_attendancepolicy WHERE id=NEW.policy_id;
    IF period.status <> 'open' OR NEW.attendance_on < period.starts_on OR NEW.attendance_on > period.ends_on
       OR policy.academic_year_id <> NEW.academic_year_id OR policy.effective_from > NEW.attendance_on THEN
        RAISE EXCEPTION 'Register must belong to an open academic year and valid policy' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' AND NEW.state <> 'draft' THEN
        RAISE EXCEPTION 'Registers must be created as drafts' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.state = 'final' OR NEW.academic_year_id <> OLD.academic_year_id OR NEW.policy_id <> OLD.policy_id OR NEW.attendance_on <> OLD.attendance_on
           OR (TG_TABLE_NAME = 'attendance_studentregister' AND to_jsonb(NEW)->>'section_id' <> to_jsonb(OLD)->>'section_id') THEN
            RAISE EXCEPTION 'Final registers and register identity are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.state = 'final' THEN
        IF TG_TABLE_NAME = 'attendance_studentregister' THEN
            SELECT count(*) INTO expected_count FROM people_enrollment
              WHERE academic_year_id=NEW.academic_year_id AND section_id=(to_jsonb(NEW)->>'section_id')::bigint
              AND started_on<=NEW.attendance_on AND (ended_on IS NULL OR ended_on>=NEW.attendance_on);
            SELECT count(*), count(*) FILTER (WHERE status='') INTO actual_count, empty_count
              FROM attendance_studentattendance WHERE register_id=NEW.id;
        ELSE
            SELECT (SELECT count(*) FROM people_teacher WHERE joined_on<=NEW.attendance_on
              AND ((is_active AND left_on IS NULL) OR left_on>=NEW.attendance_on)) +
              (SELECT count(*) FROM people_staff s WHERE joined_on<=NEW.attendance_on
              AND ((is_active AND left_on IS NULL) OR left_on>=NEW.attendance_on)
              AND NOT EXISTS (SELECT 1 FROM people_teacher t WHERE t.user_id=s.user_id AND s.user_id IS NOT NULL)) INTO expected_count;
            SELECT count(*), count(*) FILTER (WHERE status='') INTO actual_count, empty_count
              FROM attendance_staffattendance WHERE register_id=NEW.id;
        END IF;
        IF expected_count=0 OR actual_count<>expected_count OR empty_count<>0 THEN
            RAISE EXCEPTION 'A final register must contain a complete eligible roster' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_student_register_guard BEFORE INSERT OR UPDATE OR DELETE ON attendance_studentregister
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_register_guard();
CREATE TRIGGER attendance_staff_register_guard BEFORE INSERT OR UPDATE OR DELETE ON attendance_staffregister
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_register_guard();

CREATE FUNCTION schoolos_attendance_entry_guard() RETURNS trigger AS $$
DECLARE reg_state text; reg_day date; reg_year bigint; reg_section bigint; placement people_enrollment%ROWTYPE;
DECLARE correction attendance_attendancecorrection%ROWTYPE; corr_id text; person_json jsonb;
BEGIN
    IF TG_TABLE_NAME='attendance_studentattendance' THEN
        SELECT state, attendance_on, academic_year_id, section_id INTO reg_state, reg_day, reg_year, reg_section
          FROM attendance_studentregister WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.register_id ELSE NEW.register_id END FOR UPDATE;
    ELSE
        SELECT state, attendance_on, academic_year_id INTO reg_state, reg_day, reg_year
          FROM attendance_staffregister WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.register_id ELSE NEW.register_id END FOR UPDATE;
    END IF;
    IF TG_OP='DELETE' THEN
        IF reg_state='final' THEN
            RAISE EXCEPTION 'Final attendance cannot be deleted' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.attendance_on<>reg_day THEN
        RAISE EXCEPTION 'Attendance date must match its register' USING ERRCODE = '23514';
    END IF;
    IF TG_OP='UPDATE' AND (NEW.register_id<>OLD.register_id OR NEW.attendance_on<>OLD.attendance_on
      OR (to_jsonb(NEW)->'enrollment_id' IS DISTINCT FROM to_jsonb(OLD)->'enrollment_id')
      OR (to_jsonb(NEW)->'student_id' IS DISTINCT FROM to_jsonb(OLD)->'student_id')
      OR (to_jsonb(NEW)->'teacher_id' IS DISTINCT FROM to_jsonb(OLD)->'teacher_id')
      OR (to_jsonb(NEW)->'staff_id' IS DISTINCT FROM to_jsonb(OLD)->'staff_id')) THEN
        RAISE EXCEPTION 'Attendance identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME='attendance_studentattendance' THEN
        SELECT * INTO placement FROM people_enrollment WHERE id=(to_jsonb(NEW)->>'enrollment_id')::bigint;
        IF placement.student_id<>(to_jsonb(NEW)->>'student_id')::uuid OR placement.academic_year_id<>reg_year
           OR placement.section_id<>reg_section OR placement.started_on>reg_day OR (placement.ended_on IS NOT NULL AND placement.ended_on<reg_day) THEN
            RAISE EXCEPTION 'Attendance must match a dated student enrollment' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF to_jsonb(NEW)->>'teacher_id' IS NOT NULL THEN
            SELECT to_jsonb(t) INTO person_json FROM people_teacher t WHERE id=(to_jsonb(NEW)->>'teacher_id')::bigint;
        ELSE
            SELECT to_jsonb(s) INTO person_json FROM people_staff s WHERE id=(to_jsonb(NEW)->>'staff_id')::bigint;
            IF EXISTS (SELECT 1 FROM people_teacher WHERE user_id=(person_json->>'user_id')::bigint) THEN
                RAISE EXCEPTION 'Use the canonical teacher profile for this employee' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF (person_json->>'joined_on')::date>reg_day OR ((person_json->>'left_on') IS NOT NULL AND (person_json->>'left_on')::date<reg_day)
           OR (NOT (person_json->>'is_active')::boolean AND person_json->>'left_on' IS NULL) THEN
            RAISE EXCEPTION 'Staff attendance must match employment dates' USING ERRCODE = '23514';
        END IF;
        IF NEW.status='leave' AND NOT EXISTS (SELECT 1 FROM attendance_leaverequest l WHERE l.state='approved'
            AND l.starts_on<=reg_day AND l.ends_on>=reg_day AND
            ((l.teacher_id=(to_jsonb(NEW)->>'teacher_id')::bigint) OR (l.staff_id=(to_jsonb(NEW)->>'staff_id')::bigint))) THEN
            RAISE EXCEPTION 'Leave attendance requires approved leave' USING ERRCODE = '23514';
        END IF;
        IF NEW.status='closure' AND NOT EXISTS (SELECT 1 FROM attendance_calendarevent c WHERE c.academic_year_id=reg_year
            AND c.kind='closure' AND c.applies_to IN ('both','staff') AND c.starts_on<=reg_day AND c.ends_on>=reg_day) THEN
            RAISE EXCEPTION 'Closure attendance requires a calendar closure' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF reg_state='final' THEN
        IF TG_OP='INSERT' THEN
            RAISE EXCEPTION 'No rows may be appended to final registers' USING ERRCODE = '23514';
        END IF;
        corr_id := current_setting('schoolos.correction_id', true);
        IF corr_id IS NULL OR corr_id='' THEN
            RAISE EXCEPTION 'Final attendance requires an approved correction' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO correction FROM attendance_attendancecorrection WHERE id=corr_id::bigint;
        IF NOT FOUND OR correction.state<>'approved'
          OR (TG_TABLE_NAME='attendance_studentattendance' AND correction.student_entry_id IS DISTINCT FROM OLD.id)
          OR (TG_TABLE_NAME='attendance_staffattendance' AND correction.staff_entry_id IS DISTINCT FROM OLD.id)
          OR correction.before->>'status' IS DISTINCT FROM OLD.status OR correction.after->>'status' IS DISTINCT FROM NEW.status
          OR correction.before->>'notes' IS DISTINCT FROM OLD.notes OR correction.after->>'notes' IS DISTINCT FROM NEW.notes
          OR (correction.before->>'arrival_time')::time IS DISTINCT FROM OLD.arrival_time
          OR (correction.after->>'arrival_time')::time IS DISTINCT FROM NEW.arrival_time
          OR NEW.revision<>OLD.revision+1 OR NEW.recorded_by_id<>correction.reviewed_by_id THEN
            RAISE EXCEPTION 'Correction must match the original and revised values' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.revision<>0 THEN
        RAISE EXCEPTION 'Draft attendance cannot have correction revisions' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_student_entry_guard BEFORE INSERT OR UPDATE OR DELETE ON attendance_studentattendance
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_entry_guard();
CREATE TRIGGER attendance_staff_entry_guard BEFORE INSERT OR UPDATE OR DELETE ON attendance_staffattendance
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_entry_guard();

CREATE FUNCTION schoolos_attendance_decision_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Attendance decisions cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF OLD.state<>'pending' OR NEW.state NOT IN ('approved','rejected')
      OR (to_jsonb(NEW)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at']) THEN
        RAISE EXCEPTION 'Requests are immutable except for one review decision' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_correction_guard BEFORE UPDATE OR DELETE ON attendance_attendancecorrection
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_decision_guard();
CREATE TRIGGER attendance_leave_guard BEFORE UPDATE OR DELETE ON attendance_leaverequest
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_decision_guard();

CREATE FUNCTION schoolos_attendance_policy_guard() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM attendance_studentregister WHERE policy_id=OLD.id)
       OR EXISTS (SELECT 1 FROM attendance_staffregister WHERE policy_id=OLD.id) THEN
        RAISE EXCEPTION 'Attendance policy in use is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_policy_guard BEFORE UPDATE OR DELETE ON attendance_attendancepolicy
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_policy_guard();

CREATE FUNCTION schoolos_attendance_enrollment_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.ended_on IS NOT NULL AND EXISTS (SELECT 1 FROM attendance_studentattendance WHERE enrollment_id=OLD.id AND attendance_on>NEW.ended_on) THEN
        RAISE EXCEPTION 'Enrollment exit cannot invalidate attendance history' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_enrollment_guard BEFORE UPDATE ON people_enrollment
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_enrollment_guard();
"""

REVERSE = """
DROP TRIGGER attendance_enrollment_guard ON people_enrollment;
DROP TRIGGER attendance_policy_guard ON attendance_attendancepolicy;
DROP TRIGGER attendance_leave_guard ON attendance_leaverequest;
DROP TRIGGER attendance_correction_guard ON attendance_attendancecorrection;
DROP TRIGGER attendance_staff_entry_guard ON attendance_staffattendance;
DROP TRIGGER attendance_student_entry_guard ON attendance_studentattendance;
DROP TRIGGER attendance_staff_register_guard ON attendance_staffregister;
DROP TRIGGER attendance_student_register_guard ON attendance_studentregister;
DROP FUNCTION schoolos_attendance_enrollment_guard();
DROP FUNCTION schoolos_attendance_policy_guard();
DROP FUNCTION schoolos_attendance_decision_guard();
DROP FUNCTION schoolos_attendance_entry_guard();
DROP FUNCTION schoolos_attendance_register_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("attendance", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
