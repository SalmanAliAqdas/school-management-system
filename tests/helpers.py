from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from academics.models import AcademicYear, SchoolClass, Section, Subject, TeachingAssignment
from accounts.roles import sync_roles
from people.models import Enrollment, Guardian, GuardianStudent, Student, Teacher

PASSWORD = "Fictional-Test-Passphrase-409!"
BACKEND = "django.contrib.auth.backends.ModelBackend"


def make_user(username, role=None, **kwargs):
    user = get_user_model().objects.create_user(
        username, f"{username}@example.invalid", PASSWORD, **kwargs
    )
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def make_school_data():
    sync_roles()
    admin = make_user("administrator", "School Administrator")
    student_user = make_user("learner", "Student")
    parent = make_user("guardian", "Parent or Guardian")
    teacher_user = make_user("educator", "Teacher")
    accountant = make_user("finance", "Accountant")
    year = AcademicYear.objects.create(
        name="2026–2027",
        starts_on=date(2026, 8, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    old_year = AcademicYear.objects.create(
        name="2025–2026",
        starts_on=date(2025, 8, 1),
        ends_on=date(2026, 7, 31),
    )
    grade = SchoolClass.objects.create(name="Grade 6", sort_order=6)
    section = Section.objects.create(school_class=grade, name="A")
    other_section = Section.objects.create(school_class=grade, name="B")
    own = Student.objects.create(
        user=student_user, first_name="Fictional", last_name="Learner", admission_number="TEST-001"
    )
    other = Student.objects.create(
        first_name="Other", last_name="Learner", admission_number="TEST-002"
    )
    unassigned = Student.objects.create(
        first_name="Unassigned", last_name="Learner", admission_number="TEST-003"
    )
    for student, placement in ((own, section), (other, other_section)):
        Enrollment.objects.create(
            student=student, academic_year=year, section=placement, started_on=year.starts_on
        )
    Enrollment.objects.create(
        student=own,
        academic_year=old_year,
        section=other_section,
        started_on=old_year.starts_on,
        ended_on=old_year.ends_on,
        is_active=False,
    )
    guardian = Guardian.objects.create(user=parent, first_name="Fictional", last_name="Guardian")
    GuardianStudent.objects.create(guardian=guardian, student=own, relationship="Guardian")
    teacher = Teacher.objects.create(
        user=teacher_user, first_name="Fictional", last_name="Teacher", employee_number="TEST-T001"
    )
    subject = Subject.objects.create(code="TEST-MATH", name="Mathematics")
    TeachingAssignment.objects.create(
        teacher=teacher, academic_year=year, section=section, subject=subject
    )
    return {
        "admin": admin,
        "student_user": student_user,
        "parent": parent,
        "teacher_user": teacher_user,
        "accountant": accountant,
        "year": year,
        "old_year": old_year,
        "section": section,
        "other_section": other_section,
        "own": own,
        "other": other,
        "unassigned": unassigned,
        "guardian": guardian,
        "teacher": teacher,
        "subject": subject,
    }
