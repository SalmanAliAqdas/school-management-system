from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SchoolSettings(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=160, default="RumiWare SchoolOS")
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    currency = models.CharField(max_length=3, default="PKR")
    address = models.TextField(blank=True, max_length=500)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    principal_name = models.CharField(max_length=160, blank=True)
    principal_email = models.EmailField(blank=True)
    principal_phone = models.CharField(max_length=40, blank=True)
    logo = models.FileField(upload_to="private/images/", blank=True)

    class Meta:
        verbose_name_plural = "School settings"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="single_school_settings")
        ]

    def clean(self):
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError({"timezone": "Choose a valid IANA timezone."}) from exc
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise ValidationError({"currency": "Use a three-letter uppercase currency code."})

    def __str__(self):
        return self.name
