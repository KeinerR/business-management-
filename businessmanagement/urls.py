from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views, api
from .health import health_check

api_v1_router = DefaultRouter()
api_v1_router.register("financial-entries", api.FinancialEntryViewSet, basename="v1-financial-entry")
api_v1_router.register("third-parties", api.ThirdPartyViewSet, basename="v1-third-party")
api_v1_router.register("webhooks", api.WebhookEndpointViewSet, basename="v1-webhook")
api_v1_router.register("webhook-deliveries", api.WebhookDeliveryViewSet, basename="v1-webhook-delivery")

urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("", views.home, name="home"),
    path("platform/", views.platform_dashboard, name="platform_dashboard"),
    path("platform/tenants/", views.platform_tenant_list, name="platform_tenant_list"),
    path(
        "platform/tenants/<int:tenant_id>/",
        views.platform_tenant_detail,
        name="platform_tenant_detail",
    ),
    path(
        "platform/tenants/<int:tenant_id>/toggle-active/",
        views.platform_tenant_toggle_active,
        name="platform_tenant_toggle_active",
    ),
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
    path("budgets/", views.budget_list, name="budget_list"),
    path("budgets/create/", views.budget_create, name="budget_create"),
    path("budgets/<int:budget_id>/", views.budget_detail, name="budget_detail"),
    path("budgets/<int:budget_id>/edit/", views.budget_edit, name="budget_edit"),
    path("forecast/", views.forecast_dashboard, name="forecast_dashboard"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/tags/", views.document_tag_list, name="document_tag_list"),
    path("documents/tags/create/", views.document_tag_create, name="document_tag_create"),
    path(
        "documents/tags/<int:tag_id>/edit/",
        views.document_tag_edit,
        name="document_tag_edit",
    ),
    path(
        "documents/tags/<int:tag_id>/delete/",
        views.document_tag_delete,
        name="document_tag_delete",
    ),
    path("documents/create/", views.document_create, name="document_create"),
    path("documents/<int:document_id>/", views.document_detail, name="document_detail"),
    path("documents/<int:document_id>/versions/", views.document_add_version, name="document_add_version"),
    path("documents/<int:document_id>/versions/<int:version_id>/download/", views.document_download, name="document_download"),
    path("documents/<int:document_id>/archive/", views.document_archive, name="document_archive"),
    path("import/upload/", views.generic_import_upload, name="generic_import_upload"),
    path("import/preview/<int:batch_id>/", views.generic_import_preview, name="generic_import_preview"),
    path("import/confirm/<int:batch_id>/", views.generic_import_confirm, name="generic_import_confirm"),
    path("import/rollback/<int:batch_id>/", views.generic_import_rollback, name="generic_import_rollback"),
    path("import/batches/", views.generic_import_batch_list, name="generic_import_batch_list"),
    path("import/batches/<int:batch_id>/", views.generic_import_batch_detail, name="generic_import_batch_detail"),
    path("tax-rules/", views.tax_rule_list, name="tax_rule_list"),
    path("tax-rules/create/", views.tax_rule_create, name="tax_rule_create"),
    path("tax-rules/<int:tax_rule_id>/edit/", views.tax_rule_edit, name="tax_rule_edit"),

    path(
        "accounts/aging/export/",
        views.cartera_aging_excel_export,
        name="cartera_aging_excel_export",
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
    path(
        "bank/accounts/<int:account_id>/edit/",
        views.bank_account_edit,
        name="bank_account_edit",
    ),

    # Banco / Extractos / Conciliación (MVP)
    path(
        "bank/statements/import/",
        __import__("businessmanagement.services.banking", fromlist=["bank_statement_import_csv"]).bank_statement_import_csv,
        name="bank_statement_import_csv",
    ),
    # (B2) Banking se implementa en services/banking.py; si hay duplicados en views.py,
    # esta ruta debe apuntar al servicio.
    
    path(
        "bank/statements/<int:statement_id>/suggestions/",
        __import__("businessmanagement.services.banking", fromlist=["bank_transaction_suggestions"]).bank_transaction_suggestions,
        name="bank_transaction_suggestions",
    ),
    path(
        "bank/reconciliations/<int:rec_id>/confirm/",
        __import__("businessmanagement.services.banking", fromlist=["reconciliation_confirm"]).reconciliation_confirm,
        name="reconciliation_confirm",
    ),
    path("bank/statements/", views.bank_statement_list, name="bank_statement_list"),
    path("bank/reconciliations/", views.reconciliation_list, name="reconciliation_list"),
    path(
        "bank/transactions/<int:transaction_id>/manual-match/",
        __import__("businessmanagement.services.banking", fromlist=["reconciliation_manual"]).reconciliation_manual,
        name="reconciliation_manual",
    ),
    path(
        "bank/statements/<int:statement_id>/bulk-confirm/",
        __import__("businessmanagement.services.banking", fromlist=["reconciliation_bulk_confirm"]).reconciliation_bulk_confirm,
        name="reconciliation_bulk_confirm",
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
    path("accounting/accounts/", views.account_list, name="account_list"),
    path("accounting/accounts/create/", views.account_create, name="account_create"),
    path("accounting/accounts/<int:account_id>/edit/", views.account_edit, name="account_edit"),
    path("accounting/accounts/seed-puc/", views.account_seed_puc, name="account_seed_puc"),
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
    # Ajustes del Tenant
    path("settings/modules/", views.module_settings, name="module_settings"),
    
    path("audit/", views.audit_event_list, name="audit_event_list"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/read-all/", views.notification_read_all, name="notification_read_all"),
    path("notifications/<int:notification_id>/open/", views.notification_open, name="notification_open"),
    path("approvals/", views.approval_list, name="approval_list"),
    path("approvals/<int:approval_id>/", views.approval_detail, name="approval_detail"),
    path("approvals/<int:approval_id>/decide/", views.approval_decide, name="approval_decide"),
    path("approvals/request/<str:entity_type>/<int:entity_id>/", views.approval_request_create, name="approval_request_create"),
    # Cotizaciones (Quotes)
    path("quotes/", views.quote_list, name="quote_list"),
    path("quotes/create/", views.quote_create, name="quote_create"),
    path("quotes/<int:quote_id>/", views.quote_detail, name="quote_detail"),
    path("quotes/<int:quote_id>/edit/", views.quote_edit, name="quote_edit"),
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
    path("quotes/<int:quote_id>/pdf/", views.quote_pdf, name="quote_pdf"),

    # Facturas (Invoices)
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/create/", views.invoice_create, name="invoice_create"),
    path("invoices/<int:invoice_id>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:invoice_id>/edit/", views.invoice_edit, name="invoice_edit"),
    path("invoices/<int:invoice_id>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("invoices/<int:invoice_id>/issue/", views.invoice_issue, name="invoice_issue"),
    path("invoices/<int:invoice_id>/cancel/", views.invoice_cancel, name="invoice_cancel"),

    # Simple JSON API endpoints (read-only)
    # Notas de Crédito
    path("credit-notes/", views.credit_note_list, name="credit_note_list"),
    path("credit-notes/create/", views.credit_note_create, name="credit_note_create"),
    path(
        "credit-notes/<int:credit_note_id>/",
        views.credit_note_detail,
        name="credit_note_detail",
    ),
    path("credit-notes/<int:credit_note_id>/edit/", views.credit_note_edit, name="credit_note_edit"),
    path("credit-notes/<int:credit_note_id>/cancel/", views.credit_note_cancel, name="credit_note_cancel"),
    path("credit-notes/<int:credit_note_id>/pdf/", views.credit_note_pdf, name="credit_note_pdf"),
    # Notas de Débito
    path("debit-notes/", views.debit_note_list, name="debit_note_list"),
    path("debit-notes/create/", views.debit_note_create, name="debit_note_create"),
    path(
        "debit-notes/<int:debit_note_id>/",
        views.debit_note_detail,
        name="debit_note_detail",
    ),
    path("debit-notes/<int:debit_note_id>/edit/", views.debit_note_edit, name="debit_note_edit"),
    path("debit-notes/<int:debit_note_id>/cancel/", views.debit_note_cancel, name="debit_note_cancel"),

    path("debit-notes/<int:debit_note_id>/pdf/", views.debit_note_pdf, name="debit_note_pdf"),

    # API Endpoints
    path("api/v1/", include(api_v1_router.urls)),
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
