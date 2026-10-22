from django.contrib.auth import views as auth_views
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from .forms import LoginForm


@method_decorator(never_cache, name="dispatch")
class LoginView(auth_views.LoginView):
    authentication_form = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True
