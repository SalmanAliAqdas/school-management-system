from django.db import migrations
from django.db.models import Min


def backfill(apps, schema_editor):
    Student = apps.get_model("people", "Student")
    Enrollment = apps.get_model("people", "Enrollment")
    Assignment = apps.get_model("academics", "TeachingAssignment")
    ClassSubject = apps.get_model("academics", "ClassSubject")
    for student in Student.objects.all().iterator():
        earliest = Enrollment.objects.filter(student=student).aggregate(day=Min("started_on"))[
            "day"
        ]
        student.admission_date = earliest or student.created_at.date()
        if not student.is_active:
            student.status = "withdrawn"
        student.save(update_fields=["admission_date", "status"])
    for row in Assignment.objects.select_related("section").iterator():
        ClassSubject.objects.get_or_create(
            academic_year_id=row.academic_year_id,
            school_class_id=row.section.school_class_id,
            subject_id=row.subject_id,
        )


FORWARD = """
CREATE FUNCTION schoolos_enrollment_guard() RETURNS trigger AS $$
DECLARE year_row academics_academicyear%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Enrollment records cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NOT OLD.is_active OR NEW.student_id <> OLD.student_id
           OR NEW.academic_year_id <> OLD.academic_year_id OR NEW.section_id <> OLD.section_id
           OR NEW.started_on <> OLD.started_on OR NEW.roll_number <> OLD.roll_number THEN
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
CREATE TRIGGER schoolos_enrollment_guard BEFORE INSERT OR UPDATE OR DELETE ON people_enrollment
FOR EACH ROW EXECUTE FUNCTION schoolos_enrollment_guard();
"""

REVERSE = """
DROP TRIGGER schoolos_enrollment_guard ON people_enrollment;
DROP FUNCTION schoolos_enrollment_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("people", "0003_enrollment_student_placements_do_not_overlap")]
    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
