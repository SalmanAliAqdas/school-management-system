from django.db import migrations

SQL = r"""
CREATE FUNCTION phase7_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Phase 7 historical records are immutable';
END; $$;
CREATE FUNCTION phase7_entry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_id bigint; source_state varchar;
BEGIN
 source_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.timetable_id ELSE NEW.timetable_id END;
 PERFORM pg_advisory_xact_lock(715001);
 SELECT state INTO source_state FROM scheduling_timetable WHERE id=source_id;
 IF source_state <> 'draft' THEN RAISE EXCEPTION 'Published timetable lessons are protected'; END IF;
 IF TG_OP = 'UPDATE' AND OLD.timetable_id <> NEW.timetable_id THEN
  RAISE EXCEPTION 'A lesson cannot move between timetable versions';
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END; $$;
CREATE TRIGGER phase7_protect_entries BEFORE INSERT OR UPDATE OR DELETE ON scheduling_entry
FOR EACH ROW EXECUTE FUNCTION phase7_entry_guard();
CREATE TRIGGER phase7_schedule_history BEFORE UPDATE OR DELETE ON scheduling_schedulehistory
FOR EACH ROW EXECUTE FUNCTION phase7_immutable();
"""
REVERSE = """
DROP TRIGGER phase7_schedule_history ON scheduling_schedulehistory;
DROP TRIGGER phase7_protect_entries ON scheduling_entry;
DROP FUNCTION phase7_entry_guard();
DROP FUNCTION phase7_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0002_booking")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
