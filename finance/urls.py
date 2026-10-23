from django.urls import path

from . import views

app_name = "finance"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("initialize/", views.initialize_view, name="initialize"),
    path("setup/<slug:kind>/", views.setup_list, name="setup"),
    path("setup/<slug:kind>/new/", views.setup_edit, name="setup_create"),
    path("setup/<slug:kind>/<str:pk>/", views.setup_edit, name="setup_edit"),
    path("students/", views.students, name="students"),
    path("students/<uuid:pk>/", views.student_account, name="student"),
    path("invoices/", views.invoice_list, name="invoices"),
    path("invoices/<uuid:pk>/", views.invoice_detail, name="invoice"),
    path("invoices/<uuid:pk>/action/", views.invoice_action, name="invoice_action"),
    path("billing/", views.bulk_billing, name="billing"),
    path("collect/", views.collect, name="collect"),
    path("allocate/", views.allocate, name="allocate"),
    path("receipts/", views.receipts, name="receipts"),
    path("receipts/<uuid:pk>/", views.receipt, name="receipt"),
    path("requests/", views.requests, name="requests"),
    path("requests/new/", views.action_request, name="action_request"),
    path("requests/<uuid:pk>/", views.request_detail, name="request"),
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/new/", views.expense_create, name="expense_create"),
    path("expenses/<uuid:pk>/pay/", views.expense_pay, name="expense_pay"),
    path("expenses/<uuid:pk>/attachment/", views.attachment, name="attachment"),
    path("reconciliation/", views.reconcile, name="reconcile"),
    path("reports/", views.reports, name="reports"),
    path("journal/", views.journal, name="journal"),
    path("notices/", views.notices, name="notices"),
    path("reminders/", views.reminders, name="reminders"),
]
