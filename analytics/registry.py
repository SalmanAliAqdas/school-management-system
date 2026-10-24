KPI_DEFINITIONS = {
    "active_students": {
        "label": "Active students",
        "source": "people.Enrollment",
        "permission": "core.view_executive_analytics",
        "missing": "No placement means the student is excluded and flagged by data quality.",
    },
    "student_attendance": {
        "label": "Student attendance",
        "source": "attendance.StudentAttendance in finalized registers",
        "permission": "attendance.view_all_attendance",
        "missing": "Missing registers/blank entries are not converted to absences.",
    },
    "staff_attendance": {
        "label": "Staff attendance",
        "source": "attendance.StaffAttendance in finalized registers",
        "permission": "attendance.view_all_staff_attendance",
        "missing": "Leave, closure and blank entries follow the Phase 3 denominator policy.",
    },
    "published_results": {
        "label": "Published results",
        "source": "examinations.PublishedResult snapshots",
        "permission": "examinations.view_all_examinations",
        "missing": "Draft, approved-but-unpublished and withheld source marks are excluded.",
    },
    "collections": {
        "label": "Collections",
        "source": "finance.Payment posted records, excluding dated reversals",
        "permission": "finance.view_finance_reports",
        "missing": "Cash received is not presented as earned revenue.",
    },
    "payroll_obligations": {
        "label": "Payroll obligations",
        "source": "payroll.Payslip released/paid snapshots",
        "permission": "payroll.view_all_payroll",
        "missing": "Hidden entirely without confidential aggregate-payroll permission.",
    },
}
