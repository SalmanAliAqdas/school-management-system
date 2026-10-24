import base64

from .models import SchoolSettings


def school_branding():
    """Return a serialization-safe branding snapshot for generated documents."""
    school = SchoolSettings.objects.first()
    result = {
        key: getattr(school, key, "") if school else ""
        for key in ("name", "address", "phone", "email")
    }
    result["name"] = result["name"] or "RumiWare SchoolOS"
    result["logo"] = None
    if school and school.logo:
        try:
            with school.logo.open("rb") as logo:
                data = logo.read(2 * 1024 * 1024 + 1)
            if len(data) <= 2 * 1024 * 1024:
                result["logo"] = base64.b64encode(data).decode("ascii")
        except OSError:
            pass
    return result
