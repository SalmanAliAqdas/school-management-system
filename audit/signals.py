from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services import record_event


@receiver(user_logged_in)
def login_event(sender, request, user, **kwargs):
    record_event("auth.login", actor=user)


@receiver(user_logged_out)
def logout_event(sender, request, user, **kwargs):
    record_event("auth.logout", actor=user)


@receiver(user_login_failed)
def failed_login_event(sender, credentials, request, **kwargs):
    record_event("auth.login_failed")
