from django.urls import path

from . import views

app_name = "payroll"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("generate/", views.generate_view, name="generate"),
    path("runs/<int:pk>/<str:action_name>/", views.action, name="action"),
    path("payslips/<uuid:pk>/payment/", views.payment, name="payment"),
    path("payslips/<uuid:pk>/", views.payslip, name="payslip"),
]
