from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views, api

urlpatterns = [
    path("", views.home, name="home"),
    path("platform/", views.platform_dashboard, name="platform_dashboard"),
    path("platform/tenants/", views.platform_tenant_list, name="platform_tenant_list"),
    path(
        "platform/tenants/create/",
        views.platform_tenant_create,
        name="platform_tenant_create",
    ),
    path(
        "platform/tenants/<int:tenant_id>/edit/",
        views.platform_tenant_edit,
        name="platform_tenant_edit",
    ),
    path(
        "platform/tenants/<int:tenant_id>/delete/",
        views.platform_tenant_delete,
        name="platform_tenant_delete",
    ),
    path("create_business/", views.create_business, name="create_business"),
    path("business_list/", views.business_list, name="business_list"),
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/create/", views.create_employee_view, name="create_employee"),
    path(
        "employees/<int:employee_id>/edit/", views.employee_edit, name="employee_edit"
    ),
    path("users/", views.tenant_user_list, name="tenant_user_list"),
    path("users/<int:user_id>/edit/", views.tenant_user_edit, name="tenant_user_edit"),
    path("groups/", views.tenant_group_list, name="tenant_group_list"),
    path("groups/create/", views.tenant_group_create, name="tenant_group_create"),
    path(
        "groups/<int:group_id>/edit/", views.tenant_group_edit, name="tenant_group_edit"
    ),
    path("third-parties/", views.third_party_list, name="third_party_list"),
    path("third-parties/create/", views.third_party_create, name="third_party_create"),
    path(
        "third-parties/<int:third_party_id>/edit/",
        views.third_party_edit,
        name="third_party_edit",
    ),
    path(
        "third-parties/<int:third_party_id>/toggle/",
        views.third_party_toggle_active,
        name="third_party_toggle_active",
    ),
    path("finance/", views.financial_entry_list, name="financial_entry_list"),
    path("accounts/", views.cartera_dashboard, name="cartera_dashboard"),
    path(
        "finance/create/", views.financial_entry_create, name="financial_entry_create"
    ),
    path(
        "finance/<int:entry_id>/edit/",
        views.financial_entry_edit,
        name="financial_entry_edit",
    ),
    path(
        "finance/<int:entry_id>/cancel/",
        views.financial_entry_cancel,
        name="financial_entry_cancel",
    ),
    # Pagos / Reconciliación
    path("payments/", views.payment_list, name="payment_list"),
    path(
        "payments/create/<int:entry_id>/", views.payment_create, name="payment_create"
    ),

    # Banco / Extractos (MVP)
    path("bank/accounts/", views.bank_account_list, name="bank_account_list"),
    path(
        "bank/accounts/create/",
        views.bank_account_create,
        name="bank_account_create",
    ),

    # Banco / Extractos / Conciliación (MVP)
    path(
        "bank/statements/import/",
        views.bank_statement_import_csv,
        name="bank_statement_import_csv",
    ),
    path(
        "bank/statements/<int:statement_id>/suggestions/",
        views.bank_transaction_suggestions,
        name="bank_transaction_suggestions",
    ),
    path(
        "bank/reconciliations/<int:rec_id>/confirm/",
        views.reconciliation_confirm,
        name="reconciliation_confirm",
    ),

    path("projects/", views.project_list, name="project_list"),
    path("projects/create/", views.project_create, name="project_create"),
    path("projects/<int:project_id>/edit/", views.project_edit, name="project_edit"),
    path("categories/", views.financial_category_list, name="financial_category_list"),
    path(
        "categories/create/",
        views.financial_category_create,
        name="financial_category_create",
    ),
    path(
        "categories/<int:category_id>/edit/",
        views.financial_category_edit,
        name="financial_category_edit",
    ),
    path("currency-rates/", views.currency_rate_list, name="currency_rate_list"),
    path(
        "currency-rates/create/",
        views.currency_rate_create,
        name="currency_rate_create",
    ),
    path(
        "currency-rates/<int:rate_id>/edit/",
        views.currency_rate_edit,
        name="currency_rate_edit",
    ),
    path(
        "employees/<int:employee_id>/toggle-active/",
        views.employee_toggle_active,
        name="employee_toggle_active",
    ),
    path("audit/", views.audit_event_list, name="audit_event_list"),
    # Cotizaciones (Quotes)
    path("quotes/", views.quote_list, name="quote_list"),
    path("quotes/create/", views.quote_create, name="quote_create"),
    path("quotes/<int:quote_id>/", views.quote_detail, name="quote_detail"),
    path(
        "quotes/<int:quote_id>/accept/",
        views.quote_accept,
        name="quote_accept",
    ),
    path(
        "quotes/<int:quote_id>/convert/",
        views.quote_convert_to_invoice,
        name="quote_convert_to_invoice",
    ),

    # Facturas (Invoices)
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/create/", views.invoice_create, name="invoice_create"),
    path("invoices/<int:invoice_id>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:invoice_id>/edit/", views.invoice_edit, name="invoice_edit"),
    path("invoices/<int:invoice_id>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path(
        "invoices/<int:invoice_id>/delete/", views.invoice_delete, name="invoice_delete"
    ),
    # Simple JSON API endpoints (read-only)
    path(
        "api/financial-entries/",
        api.financial_entries_api,
        name="api_financial_entries",
    ),
    path("api/third-parties/", api.third_parties_api, name="api_third_parties"),
    path("api/currency-rates/", api.currency_rates_api, name="api_currency_rates"),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
]
