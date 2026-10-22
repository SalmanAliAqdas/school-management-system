from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm


class StyledFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class LoginForm(StyledFieldsMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "The username or password is incorrect.",
        "inactive": "The username or password is incorrect.",
    }


class ResetRequestForm(StyledFieldsMixin, PasswordResetForm):
    pass


class ResetPasswordForm(StyledFieldsMixin, SetPasswordForm):
    pass
