from django.utils import timezone

from attendance.calendar import school_now


class SchoolTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith(("/scheduling/", "/learning/", "/communications/"))
            and request.user.is_authenticated
        ):
            with timezone.override(school_now().tzinfo):
                return self.get_response(request)
        return self.get_response(request)
