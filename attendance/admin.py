from django.contrib import admin

from people.admin import HistoricalAdmin

from .models import (
    AbsenceNotification,
    AttendanceCorrection,
    AttendancePolicy,
    CalendarEvent,
    LeaveRequest,
    StaffAttendance,
    StaffRegister,
    StudentAttendance,
    StudentRegister,
)

for model in (
    AttendancePolicy,
    CalendarEvent,
    StudentRegister,
    StudentAttendance,
    StaffRegister,
    StaffAttendance,
    AttendanceCorrection,
    LeaveRequest,
    AbsenceNotification,
):
    admin.site.register(model, HistoricalAdmin)
