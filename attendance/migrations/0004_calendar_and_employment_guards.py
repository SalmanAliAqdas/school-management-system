from django.db import migrations

FORWARD = """
ALTER TABLE attendance_attendancepolicy ADD CONSTRAINT attendance_weekdays_shape
CHECK (jsonb_typeof(working_weekdays)='array' AND jsonb_array_length(working_weekdays)>0
       AND working_weekdays <@ '[0,1,2,3,4,5,6]'::jsonb);
CREATE FUNCTION schoolos_attendance_calendar_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Calendar history cannot be deleted' USING ERRCODE='23514';
    END IF;
    IF OLD.is_cancelled OR NOT NEW.is_cancelled OR NEW.cancellation_reason='' OR NEW.cancelled_by_id IS NULL OR NEW.cancelled_at IS NULL
      OR (to_jsonb(NEW)-ARRAY['is_cancelled','cancellation_reason','cancelled_by_id','cancelled_at','updated_at']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['is_cancelled','cancellation_reason','cancelled_by_id','cancelled_at','updated_at']) THEN
        RAISE EXCEPTION 'Calendar events may only be cancelled with a recorded reason and actor' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_calendar_guard BEFORE UPDATE OR DELETE ON attendance_calendarevent
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_calendar_guard();
CREATE FUNCTION schoolos_attendance_active_closure_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.status='closure' AND NOT EXISTS (SELECT 1 FROM attendance_calendarevent c JOIN attendance_staffregister r ON r.academic_year_id=c.academic_year_id
       WHERE r.id=NEW.register_id AND c.kind='closure' AND NOT c.is_cancelled AND c.applies_to IN ('both','staff')
       AND c.starts_on<=NEW.attendance_on AND c.ends_on>=NEW.attendance_on) THEN
        RAISE EXCEPTION 'An active calendar closure is required' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_active_closure_guard BEFORE INSERT OR UPDATE ON attendance_staffattendance
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_active_closure_guard();
CREATE FUNCTION schoolos_attendance_employment_guard() RETURNS trigger AS $$
DECLARE first_day date; last_day date;
BEGIN
    IF TG_TABLE_NAME='people_teacher' THEN
        SELECT min(attendance_on),max(attendance_on) INTO first_day,last_day FROM attendance_staffattendance WHERE teacher_id=OLD.id;
    ELSE
        SELECT min(attendance_on),max(attendance_on) INTO first_day,last_day FROM attendance_staffattendance WHERE staff_id=OLD.id;
    END IF;
    IF first_day<NEW.joined_on OR (NEW.left_on IS NOT NULL AND last_day>NEW.left_on)
       OR (last_day IS NOT NULL AND NOT NEW.is_active AND NEW.left_on IS NULL) THEN
        RAISE EXCEPTION 'Employment changes cannot invalidate attendance history' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_teacher_employment_guard BEFORE UPDATE ON people_teacher
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_employment_guard();
CREATE TRIGGER attendance_staff_employment_guard BEFORE UPDATE ON people_staff
FOR EACH ROW EXECUTE FUNCTION schoolos_attendance_employment_guard();
"""
REVERSE = """
DROP TRIGGER attendance_staff_employment_guard ON people_staff;
DROP TRIGGER attendance_teacher_employment_guard ON people_teacher;
DROP TRIGGER attendance_active_closure_guard ON attendance_staffattendance;
DROP TRIGGER attendance_calendar_guard ON attendance_calendarevent;
DROP FUNCTION schoolos_attendance_employment_guard();
DROP FUNCTION schoolos_attendance_active_closure_guard();
DROP FUNCTION schoolos_attendance_calendar_guard();
ALTER TABLE attendance_attendancepolicy DROP CONSTRAINT attendance_weekdays_shape;
"""


class Migration(migrations.Migration):
    dependencies = [("attendance", "0003_calendarevent_cancellation_reason_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
