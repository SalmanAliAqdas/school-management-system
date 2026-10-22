from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION schoolos_enrollment_guard() RETURNS trigger AS $$
DECLARE year_row academics_academicyear%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Enrollment records cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NOT OLD.is_active OR NEW.student_id <> OLD.student_id
           OR NEW.academic_year_id <> OLD.academic_year_id OR NEW.section_id <> OLD.section_id
           OR NEW.started_on <> OLD.started_on THEN
            RAISE EXCEPTION 'Historical placements and placement identity are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT * INTO year_row FROM academics_academicyear WHERE id = NEW.academic_year_id FOR UPDATE;
    IF year_row.status <> 'open' OR NEW.started_on < year_row.starts_on
       OR NEW.started_on > year_row.ends_on
       OR (NEW.ended_on IS NOT NULL AND NEW.ended_on > year_row.ends_on) THEN
        RAISE EXCEPTION 'Enrollment dates must belong to an open academic year' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
REVERSE = FUNCTION.replace(
    "NEW.started_on <> OLD.started_on THEN",
    "NEW.started_on <> OLD.started_on OR NEW.roll_number <> OLD.roll_number THEN",
)


class Migration(migrations.Migration):
    dependencies = [("people", "0004_backfill_and_protect_history")]
    operations = [migrations.RunSQL(FUNCTION, REVERSE)]
