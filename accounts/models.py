from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.functions import Lower


class SchoolUserManager(UserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        return super()._create_user_object(username, email.lower(), password, **extra_fields)


class User(AbstractUser):
    email = models.EmailField(unique=True)
    objects = SchoolUserManager()
    REQUIRED_FIELDS = ["email"]

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
            models.CheckConstraint(condition=~models.Q(email=""), name="user_email_not_blank"),
        ]
        permissions = [
            ("access_admin_dashboard", "Can access administration dashboard"),
            ("access_teacher_dashboard", "Can access teacher dashboard"),
            ("access_student_dashboard", "Can access student dashboard"),
            ("access_parent_dashboard", "Can access guardian dashboard"),
        ]

    def clean(self):
        super().clean()
        self.email = self.email.lower()

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username
