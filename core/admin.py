from django.contrib import admin

from .forms import SchoolSettingsForm
from .models import SchoolSettings


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    form = SchoolSettingsForm
