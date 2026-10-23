from django.db import migrations

SQL = """
CREATE FUNCTION phase7_timetable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.state <> 'draft' AND
    ROW(NEW.title,NEW.academic_year_id,NEW.term_id,NEW.starts_on,NEW.ends_on)
    IS DISTINCT FROM ROW(OLD.title,OLD.academic_year_id,OLD.term_id,OLD.starts_on,OLD.ends_on) THEN
  RAISE EXCEPTION 'Published timetable definitions are immutable';
 END IF;
 IF OLD.state <> 'draft' AND NEW.state='draft' THEN
  RAISE EXCEPTION 'Copy a new draft instead of reopening a published version';
 END IF;
 IF NEW.state='published' AND EXISTS (
  SELECT 1 FROM scheduling_entry e WHERE e.timetable_id=NEW.id AND NOT EXISTS
  (SELECT 1 FROM scheduling_booking b WHERE b.entry_id=e.id AND b.active)
 ) THEN RAISE EXCEPTION 'Published lessons require protected resource bookings'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER phase7_timetable_definition BEFORE UPDATE ON scheduling_timetable
FOR EACH ROW EXECUTE FUNCTION phase7_timetable_guard();
CREATE FUNCTION phase7_period_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM scheduling_entry WHERE period_id=OLD.id) THEN
  RAISE EXCEPTION 'Used timetable periods are protected';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER phase7_period_definition BEFORE UPDATE ON scheduling_period
FOR EACH ROW EXECUTE FUNCTION phase7_period_guard();
CREATE TRIGGER phase7_assignment_access_history BEFORE UPDATE OR DELETE ON scheduling_assignmentaccessevent
FOR EACH ROW EXECUTE FUNCTION phase7_immutable();
"""
REVERSE = """
DROP TRIGGER phase7_assignment_access_history ON scheduling_assignmentaccessevent;
DROP TRIGGER phase7_period_definition ON scheduling_period;
DROP FUNCTION phase7_period_guard();
DROP TRIGGER phase7_timetable_definition ON scheduling_timetable;
DROP FUNCTION phase7_timetable_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0004_assignmentaccessevent")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
