"""Shared authorization and safe form error handling for school operations."""

from django.core.exceptions import PermissionDenied, ValidationError


def require_capability(actor, permission, *, student_scope=False):
    if not actor.is_authenticated or not actor.is_active or not actor.has_perm(permission):
        raise PermissionDenied
    if student_scope and not actor.has_perms(["people.view_student", "people.view_all_students"]):
        raise PermissionDenied


def form_errors(form, error):
    if isinstance(error, ValidationError) and hasattr(error, "message_dict"):
        for key, errors in error.message_dict.items():
            form.add_error(key if key in form.fields else None, errors)
    elif isinstance(error, ValidationError):
        form.add_error(None, error)
    else:
        form.add_error(None, "A conflicting record was saved. Review your entries and try again.")


def positive_id(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if 0 < number <= 9223372036854775807 else 0
