from .base import *

if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Production SECRET_KEY must contain at least 50 characters.")
if DEBUG or ALLOW_DEMO_DATA:
    raise ImproperlyConfigured("Production must disable DEBUG and fictional demo data.")
if os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
if env_bool("TRUST_PROXY_HTTPS"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
