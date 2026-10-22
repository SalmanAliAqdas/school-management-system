from django.apps import apps
from django.contrib import admin

from people.admin import HistoricalAdmin

for model in apps.get_app_config("examinations").get_models():
    admin.site.register(model, HistoricalAdmin)
