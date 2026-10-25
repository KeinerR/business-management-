from datetime import date
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
import hashlib
import hmac
import json

from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.loader import get_template
from django.urls import resolve
from openpyxl import Workbook
from rest_framework.test import APIClient
from unittest.mock import Mock, patch

from businessmanagement.forms import (
    DocumentCreateForm,
    InvoiceForm,
    PlatformTenantEditForm,
    QuoteForm,
    TaxRuleForm,
)
from businessmanagement.services.banking import (
    _confirm_reconciliation,
    _parse_csv_date,
    _rows_from_uploaded_file,
)
from businessmanagement.views import (
    _aging_bucket,
    _cancel_invoice,
    _convert_quote_to_invoice,
    _issue_invoice,
    _portfolio_risk,
    _sync_payment_status,
)
from businessmanagement.models import Tenant
from businessmanagement.modules import AVAILABLE_MODULES
from businessmanagement.tasks import deliver_webhook, mark_expired_quotes_for_current_schema
from businessmanagement.services.notifications import notify_users
from businessmanagement.services.accounting import PUC_STARTER, seed_puc_starter
from businessmanagement.services.forecast import budget_performance, cashflow_forecast
from businessmanagement.services.document_management import add_document_version
from businessmanagement.services.imports import confirm_batch, preview_batch, read_import_rows, rollback_batch
from tenantdata.models import (
    Business,
    CurrencyRate,
    DebitNote,
    DebitNoteItem,
    BankAccount,
    BankStatement,
    BankTransaction,
    AuditEvent,
    FinancialEntry,
    Invoice,
    InvoiceItem,
    Payment,
    Notification,
    ApprovalRequest,
    Account,
    Employee,
    Budget,
    BudgetLine,
    FinancialCategory,
    Quote,
    QuoteItem,
    Reconciliation,
    TaxRule,
    ThirdParty,
    Document,
    DocumentTag,
    DocumentVersion,
    ImportBatch,
    ImportedRecord,
    Project,
    WebhookDelivery,
    WebhookEndpoint,
)


class BusinessFlowTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de pruebas"
        tenant.enabled_modules = [
            "invoices",
            "quotes",
            "taxes",
            "banking",
            "finances",
            "third_parties",
        ]
        return tenant

    def setUp(self):
        self.business = Business.objects.create(
            name_business_owner="Prueba",
            last_name_business_owner="Sistema",
            business_name="Empresa de Pruebas SAS",
            business_phone="3000000000",
            business_email="tests@example.com",
            business_address="Bogotá",
        )

    def test_invoice_totals_apply_tax_and_retention_rules(self):
        iva = TaxRule.objects.create(
            business=self.business,
            name="IVA 19%",
            rule_type=TaxRule.IVA,
            percentage=Decimal("19.00"),
        )
        retention = TaxRule.objects.create(
            business=self.business,
            name="Retefuente 2.5%",
            rule_type=TaxRule.RETENCION_FUENTE,
            percentage=Decimal("2.50"),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            issue_date=date(2026, 10, 22),
        )
        invoice.tax_rules.set([iva, retention])

        invoice.calculate_totals(Decimal("100.00"))

        self.assertEqual(invoice.tax_amount, Decimal("19.00"))
        self.assertEqual(invoice.retention_amount, Decimal("2.50"))
        self.assertEqual(invoice.total, Decimal("116.50"))

    def test_document_numbers_use_distinct_prefixes(self):
        invoice = Invoice.objects.create(
            business=self.business,
            issue_date=date(2026, 10, 22),
        )
        quote = Quote.objects.create(
            business=self.business,
            issue_date=date(2026, 10, 22),
        )

        self.assertTrue(invoice.invoice_number.startswith("FAC-"))
        self.assertTrue(quote.quote_number.startswith("QUO-"))

    def test_invoice_and_quote_reject_due_date_before_issue_date(self):
        common_data = {
            "status": "draft",
            "issue_date": "2026-10-22",
            "due_date": "2026-10-21",
            "currency": "COP",
            "description": "",
            "notes": "",
        }

        invoice_form = InvoiceForm(data=common_data)
        quote_form = QuoteForm(data=common_data)

        self.assertFalse(invoice_form.is_valid())
        self.assertIn("due_date", invoice_form.errors)
        self.assertFalse(quote_form.is_valid())
        self.assertIn("due_date", quote_form.errors)

    def test_tax_percentage_must_be_in_valid_range(self):
        form = TaxRuleForm(
            data={
                "name": "IVA inválido",
                "rule_type": TaxRule.IVA,
                "percentage": "101",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("percentage", form.errors)

    def test_bank_csv_parser_accepts_colombian_dates(self):
        self.assertEqual(_parse_csv_date("22/10/2026"), date(2026, 10, 22))
        self.assertEqual(_parse_csv_date("2026-10-22"), date(2026, 10, 22))
        self.assertIsNone(_parse_csv_date("fecha-invalida"))

    def test_bank_import_reads_excel_headers_and_rows(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Fecha", "Monto", "Moneda", "Descripción"])
        sheet.append(["23/10/2026", -250000, "COP", "Pago proveedor"])
        content = BytesIO()
        workbook.save(content)
        uploaded = SimpleUploadedFile(
            "extracto.xlsx",
            content.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        rows = _rows_from_uploaded_file(uploaded)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fecha"], "23/10/2026")
        self.assertEqual(rows[0]["monto"], -250000)
        self.assertEqual(rows[0]["descripcion"], "Pago proveedor")

    def test_portfolio_aging_and_risk_classification(self):
        self.assertEqual(_aging_bucket(0), "current")
        self.assertEqual(_aging_bucket(30), "days_1_30")
        self.assertEqual(_aging_bucket(31), "days_31_60")
        self.assertEqual(_aging_bucket(91), "days_90_plus")
        self.assertEqual(
            _portfolio_risk(Decimal("0"), Decimal("100"), 0),
            ("low", "Bajo"),
        )
        self.assertEqual(
            _portfolio_risk(Decimal("10"), Decimal("100"), 15),
            ("medium", "Medio"),
        )
        self.assertEqual(
            _portfolio_risk(Decimal("60"), Decimal("100"), 20),
            ("high", "Alto"),
        )

    def test_expired_quote_automation_preserves_final_statuses(self):
        expired_draft = Quote.objects.create(
            business=self.business,
            status=Quote.DRAFT,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 9, 30),
        )
        converted = Quote.objects.create(
            business=self.business,
            status=Quote.CONVERTED,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 9, 30),
        )

        count = mark_expired_quotes_for_current_schema(date(2026, 10, 23))

        expired_draft.refresh_from_db()
        converted.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(expired_draft.status, Quote.EXPIRED)
        self.assertEqual(converted.status, Quote.CONVERTED)

    def test_quote_conversion_copies_totals_and_is_idempotent(self):
        user = get_user_model().objects.create_user(
            username="conversion-test", password="test-password"
        )
        iva = TaxRule.objects.create(
            business=self.business,
            name="IVA 19%",
            rule_type=TaxRule.IVA,
            percentage=Decimal("19.00"),
        )
        retention = TaxRule.objects.create(
            business=self.business,
            name="Retefuente 2.5%",
            rule_type=TaxRule.RETENCION_FUENTE,
            percentage=Decimal("2.50"),
        )
        quote = Quote.objects.create(
            business=self.business,
            status=Quote.ACCEPTED,
            issue_date=date(2026, 10, 23),
            due_date=date(2026, 11, 23),
            created_by=user,
        )
        quote.tax_rules.set([iva, retention])
        QuoteItem.objects.create(
            quote=quote,
            description="Servicio de implementación",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            subtotal=Decimal("100.00"),
        )
        quote.calculate_totals(Decimal("100.00"))
        quote.save(
            update_fields=["subtotal", "tax_amount", "retention_amount", "total"]
        )

        invoice, financial_entry = _convert_quote_to_invoice(quote, user)
        second_invoice, second_entry = _convert_quote_to_invoice(quote, user)

        self.assertEqual(invoice.pk, second_invoice.pk)
        self.assertEqual(financial_entry.pk, second_entry.pk)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoiceItem.objects.count(), 1)
        self.assertEqual(FinancialEntry.objects.count(), 1)
        self.assertEqual(invoice.subtotal, Decimal("100.00"))
        self.assertEqual(invoice.tax_amount, Decimal("19.00"))
        self.assertEqual(invoice.retention_amount, Decimal("2.50"))
        self.assertEqual(invoice.total, Decimal("116.50"))
        self.assertEqual(financial_entry.amount, invoice.total)
        self.assertEqual(invoice.tax_rules.count(), 2)
        self.assertEqual(quote.status, Quote.CONVERTED)

    def test_payment_status_marks_linked_invoice_as_paid(self):
        entry = FinancialEntry.objects.create(
            business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PENDING,
            concept="Factura de prueba",
            amount=Decimal("100.00"),
            currency="COP",
            entry_date=date(2026, 10, 23),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            financial_entry=entry,
            status=Invoice.ISSUED,
            issue_date=date(2026, 10, 23),
        )

        _sync_payment_status(entry, Decimal("40.00"))
        invoice.refresh_from_db()
        self.assertEqual(entry.status, FinancialEntry.PARTIAL)
        self.assertEqual(invoice.status, Invoice.ISSUED)

        _sync_payment_status(entry, Decimal("100.00"))
        invoice.refresh_from_db()
        self.assertEqual(entry.status, FinancialEntry.PAID)
        self.assertEqual(invoice.status, Invoice.PAID)

    def test_manual_reconciliation_creates_payment_and_updates_status(self):
        user = get_user_model().objects.create_user(username="bank-user")
        account = BankAccount.objects.create(
            business=self.business,
            name="Cuenta principal",
            base_currency="COP",
        )
        statement = BankStatement.objects.create(
            bank_account=account, created_by=user, source="xlsx"
        )
        bank_transaction = BankTransaction.objects.create(
            statement=statement,
            transaction_date=date(2026, 10, 23),
            description="Pago factura",
            amount=Decimal("100.00"),
            currency="COP",
            direction="in",
        )
        entry = FinancialEntry.objects.create(
            business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PENDING,
            concept="Factura de prueba",
            amount=Decimal("100.00"),
            currency="COP",
            entry_date=date(2026, 10, 23),
        )
        reconciliation = Reconciliation.objects.create(
            bank_transaction=bank_transaction,
            financial_entry=entry,
            status=Reconciliation.PROPOSED,
        )

        _confirm_reconciliation(reconciliation, user)

        reconciliation.refresh_from_db()
        bank_transaction.refresh_from_db()
        entry.refresh_from_db()
        self.assertIsNotNone(reconciliation.payment_id)
        self.assertEqual(reconciliation.status, Reconciliation.CONFIRMED)
        self.assertEqual(bank_transaction.status, BankTransaction.RECONCILED)
        self.assertEqual(entry.status, FinancialEntry.PAID)

    def test_invoice_issue_creates_single_receivable(self):
        user = get_user_model().objects.create_user(username="invoice-user")
        invoice = Invoice.objects.create(
            business=self.business,
            status=Invoice.DRAFT,
            issue_date=date(2026, 10, 23),
            due_date=date(2026, 11, 23),
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description="Servicio",
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )

        entry = _issue_invoice(invoice, user)
        second_entry = _issue_invoice(invoice, user)

        invoice.refresh_from_db()
        self.assertEqual(entry.pk, second_entry.pk)
        self.assertEqual(invoice.status, Invoice.ISSUED)
        self.assertEqual(invoice.financial_entry_id, entry.pk)
        self.assertEqual(entry.entry_type, FinancialEntry.ACCOUNT_RECEIVABLE)
        self.assertEqual(entry.amount, invoice.total)
        self.assertEqual(FinancialEntry.objects.count(), 1)

    def test_invoice_with_payments_cannot_be_cancelled(self):
        entry = FinancialEntry.objects.create(
            business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PARTIAL,
            concept="Factura con abono",
            amount=Decimal("100.00"),
            currency="COP",
            entry_date=date(2026, 10, 23),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            financial_entry=entry,
            status=Invoice.ISSUED,
            issue_date=date(2026, 10, 23),
        )
        Payment.objects.create(
            financial_entry=entry,
            payment_date=date(2026, 10, 23),
            amount=Decimal("20.00"),
            currency="COP",
        )

        with self.assertRaisesMessage(ValueError, "nota crédito"):
            _cancel_invoice(invoice)

        invoice.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.ISSUED)
        self.assertEqual(entry.status, FinancialEntry.PARTIAL)

    def test_notifications_are_deduplicated_per_recipient(self):
        admin = get_user_model().objects.create_superuser(
            username="notification-admin", password="test-password"
        )

        notify_users(
            title="Factura vencida",
            message="Primer mensaje",
            entity="invoice",
            entity_id="10",
            dedupe_key="invoice-overdue-10",
        )
        notify_users(
            title="Factura vencida",
            message="Mensaje actualizado",
            entity="invoice",
            entity_id="10",
            dedupe_key="invoice-overdue-10",
        )

        notifications = Notification.objects.filter(recipient=admin)
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().message, "Mensaje actualizado")

    def test_only_one_pending_approval_is_allowed_per_document(self):
        user = get_user_model().objects.create_user(username="requester")
        quote = Quote.objects.create(
            business=self.business,
            issue_date=date(2026, 10, 23),
            total=Decimal("500.00"),
        )
        ApprovalRequest.objects.create(
            business=self.business,
            entity_type=ApprovalRequest.QUOTE,
            entity_id=quote.pk,
            title=quote.quote_number,
            amount=quote.total,
            currency=quote.currency,
            requested_by=user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ApprovalRequest.objects.create(
                    business=self.business,
                    entity_type=ApprovalRequest.QUOTE,
                    entity_id=quote.pk,
                    title=quote.quote_number,
                    requested_by=user,
                )

        first = ApprovalRequest.objects.get(entity_id=quote.pk)
        first.status = ApprovalRequest.APPROVED
        first.save(update_fields=["status"])
        replacement = ApprovalRequest.objects.create(
            business=self.business,
            entity_type=ApprovalRequest.QUOTE,
            entity_id=quote.pk,
            title=quote.quote_number,
            requested_by=user,
        )
        self.assertEqual(replacement.status, ApprovalRequest.PENDING)

    def test_puc_seed_is_idempotent_and_hierarchical(self):
        created, total = seed_puc_starter(self.business)
        created_again, total_again = seed_puc_starter(self.business)

        self.assertEqual(created, len(PUC_STARTER))
        self.assertEqual(total, len(PUC_STARTER))
        self.assertEqual(created_again, 0)
        self.assertEqual(total_again, total)
        self.assertEqual(Account.objects.count(), total)
        cash = Account.objects.get(code="110505")
        self.assertEqual(cash.parent.code, "1105")
        self.assertTrue(cash.accepts_entries)

    def test_financial_operator_can_load_initial_puc(self):
        self.tenant.enabled_modules.append("chart_accounts")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="puc-operator")
        group, _ = Group.objects.get_or_create(name="Operador financiero")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        response = client.post("/accounting/accounts/seed-puc/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Account.objects.count(), len(PUC_STARTER))

    def test_financial_operator_can_create_project(self):
        self.tenant.enabled_modules.append("projects")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="project-operator")
        group, _ = Group.objects.get_or_create(name="Operador financiero")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        response = client.post(
            "/projects/create/",
            {
                "name": "Proyecto de prueba",
                "description": "Proyecto creado por operaciones",
                "project_type": Project.COMPANY,
                "status": Project.ACTIVE,
                "start_date": "",
                "end_date": "",
                "third_party": "",
                "owner": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Project.objects.filter(name="Proyecto de prueba").exists())

    def test_financial_operator_can_view_tax_rules(self):
        user = get_user_model().objects.create_user(username="tax-operator")
        group, _ = Group.objects.get_or_create(name="Operador financiero")
        user.groups.add(group)
        TaxRule.objects.create(
            business=self.business,
            name="IVA de prueba",
            rule_type=TaxRule.IVA,
            percentage=Decimal("19"),
        )
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        response = client.get("/tax-rules/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IVA de prueba")
        self.assertNotContains(response, "Nueva regla")

    def test_tenant_admin_can_view_modules_and_create_debit_notes(self):
        self.tenant.enabled_modules.extend(["debit_notes", "projects"])
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="modules-admin")
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        modules_response = client.get("/settings/modules/")
        debit_list_response = client.get("/debit-notes/")
        debit_create_response = client.get("/debit-notes/create/")

        self.assertEqual(modules_response.status_code, 200)
        self.assertContains(modules_response, "Proyectos")
        self.assertEqual(debit_list_response.status_code, 200)
        self.assertContains(debit_list_response, "Nueva nota de débito")
        self.assertEqual(debit_create_response.status_code, 200)
        self.assertContains(debit_create_response, "Guardar nota de débito")
        self.assertContains(debit_create_response, "Agregar ítem")

    def test_every_tenant_module_gates_its_page_and_sidebar_link(self):
        module_pages = (
            ("finances", "/finance/"),
            ("projects", "/projects/"),
            ("third_parties", "/third-parties/"),
            ("categories", "/categories/"),
            ("invoices", "/invoices/"),
            ("quotes", "/quotes/"),
            ("employees", "/employees/"),
            ("currency_rates", "/currency-rates/"),
            ("credit_notes", "/credit-notes/"),
            ("debit_notes", "/debit-notes/"),
            ("taxes", "/tax-rules/"),
            ("banking", "/bank/accounts/"),
            ("bank_statements", "/bank/statements/"),
            ("reconciliations", "/bank/reconciliations/"),
            ("budget", "/budgets/"),
            ("cartera", "/accounts/"),
            ("payments", "/payments/"),
            ("import_batch", "/import/batches/"),
            ("audit", "/audit/"),
            ("users", "/users/"),
            ("groups", "/groups/"),
            ("notifications", "/notifications/"),
            ("approvals", "/approvals/"),
            ("chart_accounts", "/accounting/accounts/"),
            ("documents", "/documents/"),
        )
        self.assertEqual({module for module, _ in module_pages}, {
            module for module, _label in AVAILABLE_MODULES
        })
        self.tenant.enabled_modules = [module for module, _label in AVAILABLE_MODULES]
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="module-matrix-admin")
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        enabled_dashboard = client.get("/dashboard/")
        self.assertEqual(enabled_dashboard.status_code, 200)
        disabled_paths = []
        for module, path in module_pages:
            with self.subTest(module=module):
                self.assertIn(
                    module,
                    getattr(resolve(path).func, "required_modules", ()),
                )
                self.assertContains(enabled_dashboard, f'href="{path}"')
                disabled_paths.append(path)

        self.assertEqual(client.get("/finance/").status_code, 200)
        self.tenant.enabled_modules = []
        self.tenant.save(update_fields=["enabled_modules"])
        disabled_dashboard = client.get("/dashboard/")
        self.assertEqual(disabled_dashboard.status_code, 200)
        for path in disabled_paths:
            with self.subTest(path=path):
                self.assertNotContains(disabled_dashboard, f'href="{path}"')

        blocked_response = client.get("/finance/")
        self.assertEqual(blocked_response.status_code, 302)
        self.assertEqual(blocked_response.url, "/dashboard/")

    def test_tenant_superuser_cannot_bypass_disabled_module_or_admin_role(self):
        self.tenant.enabled_modules = []
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_superuser(
            username="tenant-superuser",
            email="tenant-superuser@example.com",
            password="test-password",
        )
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        response = client.get("/finance/")
        settings_response = client.get("/settings/modules/")
        api_response = client.get("/api/v1/financial-entries/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")
        self.assertEqual(settings_response.status_code, 302)
        self.assertEqual(settings_response.url, "/dashboard/")
        self.assertEqual(api_response.status_code, 403)

    def test_disabled_modules_block_corresponding_api_endpoints(self):
        self.tenant.enabled_modules = []
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="module-api-admin")
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        for path in (
            "/api/financial-entries/",
            "/api/third-parties/",
            "/api/currency-rates/",
            "/api/v1/financial-entries/",
            "/api/v1/third-parties/",
            "/api/v1/webhooks/",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 403)

    def test_tenant_operator_cannot_manage_users_groups_or_module_settings(self):
        self.tenant.enabled_modules = [
            "finances",
            "users",
            "groups",
            "audit",
        ]
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="module-operator")
        group, _ = Group.objects.get_or_create(name="Operador financiero")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        for path in ("/users/", "/groups/", "/audit/", "/settings/modules/"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, "/dashboard/")

    def test_read_only_tenant_role_cannot_create_financial_records(self):
        user = get_user_model().objects.create_user(username="module-read-only")
        group, _ = Group.objects.get_or_create(name="Solo lectura")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        page_response = client.post("/finance/create/", {})
        api_response = client.post(
            "/api/v1/financial-entries/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="read-only-finance-001",
        )

        self.assertEqual(page_response.status_code, 302)
        self.assertEqual(page_response.url, "/dashboard/")
        self.assertEqual(api_response.status_code, 403)
        self.assertFalse(FinancialEntry.objects.exists())

    def test_platform_staff_are_not_exposed_as_tenant_employees_or_users(self):
        self.tenant.enabled_modules.extend(["employees", "users"])
        self.tenant.save(update_fields=["enabled_modules"])
        tenant_admin = get_user_model().objects.create_user(
            username="tenant-data-admin"
        )
        admin_group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        tenant_admin.groups.add(admin_group)
        platform_user = get_user_model().objects.create_user(
            username="platform-owner",
            is_staff=True,
            is_superuser=True,
        )
        Employee.objects.create(
            user=platform_user,
            first_name="Dueño",
            last_name="Plataforma",
            email="platform@example.com",
            phone="3000000000",
            position="Administrador Global",
            business=self.business,
        )
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(tenant_admin)

        employees_response = client.get("/employees/")
        users_response = client.get("/users/")
        employee_edit_response = client.get(
            f"/employees/{platform_user.employee_profile.pk}/edit/"
        )
        toggle_response = client.post(
            f"/employees/{platform_user.employee_profile.pk}/toggle-active/"
        )
        user_edit_response = client.get(f"/users/{platform_user.pk}/edit/")

        self.assertEqual(employees_response.status_code, 200)
        self.assertNotContains(employees_response, "platform-owner")
        self.assertEqual(users_response.status_code, 200)
        self.assertNotContains(users_response, "platform-owner")
        self.assertEqual(employee_edit_response.status_code, 302)
        self.assertEqual(toggle_response.status_code, 302)
        self.assertTrue(
            get_user_model().objects.get(pk=platform_user.pk).is_active
        )
        self.assertEqual(user_edit_response.status_code, 302)

    def test_document_create_uses_tenant_labels_and_related_record_select(self):
        self.tenant.enabled_modules.append("documents")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="document-admin")
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        tag = DocumentTag.objects.create(business=self.business, name="Contratos")
        labels_field = DocumentCreateForm(business=self.business)["labels"]
        self.assertIn('type="checkbox"', str(labels_field))
        self.assertIn("Contratos", str(labels_field))
        party = ThirdParty.objects.create(name="Proveedor relacionado")
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        form_response = client.get("/documents/create/")
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, "Subir documento")

        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            response = client.post(
                "/documents/create/",
                {
                    "title": "Contrato de prueba",
                    "document_type": Document.CONTRACT,
                    "description": "Documento relacionado",
                    "labels": [str(tag.pk)],
                    "entity_type": "third_party",
                    "entity_id": str(party.pk),
                    "version_notes": "",
                    "file": SimpleUploadedFile(
                        "contrato.pdf", b"%PDF test", content_type="application/pdf"
                    ),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, 302)
            document = Document.objects.get(title="Contrato de prueba")
            self.assertEqual(list(document.labels.all()), [tag])
            self.assertEqual(document.related_object, party)

    def test_tenant_admin_can_open_employee_creation(self):
        self.tenant.enabled_modules.append("employees")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="employee-admin")
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)

        response = client.get("/employees/create/")

        self.assertEqual(response.status_code, 200)

    def test_tenant_admin_can_log_in_without_employee_profile(self):
        user = get_user_model().objects.create_user(
            username="tenant-admin-login",
            password="test-password",
        )
        group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(group)
        client = APIClient(HTTP_HOST=self.domain.domain)

        response = client.post(
            "/login/",
            {"username": "tenant-admin-login", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")
        self.assertEqual(int(client.session["_auth_user_id"]), user.pk)

    def test_account_code_must_extend_parent_code(self):
        parent = Account.objects.create(
            business=self.business,
            code="1",
            name="Activo",
            account_type=Account.ASSET,
            nature=Account.DEBIT,
            accepts_entries=False,
        )
        invalid = Account(
            business=self.business,
            code="2205",
            name="Cuenta inválida",
            account_type=Account.ASSET,
            nature=Account.DEBIT,
            parent=parent,
        )

        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_budget_performance_compares_expenses_by_category(self):
        category = FinancialCategory.objects.create(
            business=self.business, name="Servicios", category_type=FinancialCategory.EXPENSE
        )
        budget = Budget.objects.create(
            business=self.business,
            name="Presupuesto Q4",
            period_start_date=date(2026, 10, 1),
            period_end_date=date(2026, 12, 31),
            currency="COP",
        )
        BudgetLine.objects.create(
            budget=budget,
            category=category,
            concept="Servicios",
            budgeted_amount=Decimal("1000.00"),
            currency="COP",
        )
        FinancialEntry.objects.create(
            business=self.business,
            category=category,
            entry_type=FinancialEntry.EXPENSE,
            status=FinancialEntry.PAID,
            concept="Hosting",
            amount=Decimal("850.00"),
            currency="COP",
            entry_date=date(2026, 10, 23),
        )

        rows, totals = budget_performance(budget)

        self.assertEqual(rows[0]["actual"], Decimal("850.00"))
        self.assertEqual(rows[0]["variance"], Decimal("150.00"))
        self.assertEqual(rows[0]["risk"], "warning")
        self.assertEqual(totals[0]["budgeted"], Decimal("1000.00"))

    def test_cashflow_forecast_uses_remaining_portfolio_balance(self):
        receivable = FinancialEntry.objects.create(
            business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PARTIAL,
            concept="Cliente",
            amount=Decimal("1000.00"),
            currency="COP",
            entry_date=date(2026, 10, 1),
            due_date=date(2026, 11, 15),
        )
        Payment.objects.create(
            financial_entry=receivable,
            payment_date=date(2026, 10, 20),
            amount=Decimal("250.00"),
            currency="COP",
        )
        FinancialEntry.objects.create(
            business=self.business,
            entry_type=FinancialEntry.ACCOUNT_PAYABLE,
            status=FinancialEntry.PENDING,
            concept="Proveedor",
            amount=Decimal("300.00"),
            currency="COP",
            entry_date=date(2026, 10, 1),
            due_date=date(2026, 11, 20),
        )

        rows = cashflow_forecast(
            self.business, date(2026, 11, 1), date(2026, 11, 30)
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["incoming"], Decimal("750.00"))
        self.assertEqual(rows[0]["outgoing"], Decimal("300.00"))
        self.assertEqual(rows[0]["net"], Decimal("450.00"))

    def test_document_versions_are_sequential_and_keep_metadata(self):
        user = get_user_model().objects.create_user(username="document-user")
        document = Document.objects.create(
            business=self.business,
            title="Contrato proveedor",
            document_type=Document.CONTRACT,
            created_by=user,
        )
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            first = add_document_version(
                document,
                SimpleUploadedFile("contrato.pdf", b"version uno", content_type="application/pdf"),
                user,
                "Original",
            )
            second = add_document_version(
                document,
                SimpleUploadedFile("contrato firmado.pdf", b"version dos", content_type="application/pdf"),
                user,
                "Firmado",
            )

            self.assertEqual((first.version, second.version), (1, 2))
            self.assertEqual(DocumentVersion.objects.filter(document=document).count(), 2)
            self.assertEqual(second.original_name, "contrato firmado.pdf")
            self.assertEqual(second.notes, "Firmado")

    def test_document_version_number_cannot_be_repeated(self):
        document = Document.objects.create(
            business=self.business,
            title="Política interna",
            document_type=Document.HR,
        )
        DocumentVersion.objects.create(document=document, version=1, file="documents/test.pdf", original_name="test.pdf")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentVersion.objects.create(document=document, version=1, file="documents/test2.pdf", original_name="test2.pdf")

    def test_generic_import_preview_confirm_and_rollback(self):
        user = get_user_model().objects.create_user(username="import-user")
        batch = ImportBatch.objects.create(
            business=self.business,
            created_by=user,
            file_name="terceros.csv",
            target_model=ImportBatch.THIRD_PARTY,
            total_rows=2,
        )
        ImportedRecord.objects.create(batch=batch, row_data={"name": "Proveedor Uno", "identification": "900001", "third_party_type": "supplier", "email": "compras@example.com"})
        ImportedRecord.objects.create(batch=batch, row_data={"name": "", "identification": "900002", "email": "correo-invalido"})

        preview_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.PREVIEWED)
        self.assertEqual(batch.processed_rows, 1)
        self.assertEqual(batch.failed_rows, 1)

        confirm_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.CONFIRMED)
        self.assertTrue(ThirdParty.objects.filter(identification="900001").exists())
        self.assertEqual(batch.records.filter(status=ImportedRecord.PROCESSED).count(), 1)

        rollback_batch(batch, user)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.ROLLED_BACK)
        self.assertFalse(ThirdParty.objects.filter(identification="900001").exists())
        self.assertEqual(batch.records.filter(status=ImportedRecord.ROLLED_BACK).count(), 1)

    def test_generic_csv_reader_normalizes_headers_and_skips_empty_rows(self):
        uploaded = SimpleUploadedFile(
            "movimientos.csv",
            "Concepto;Monto;Fecha\nHosting;125000,50;23/10/2026\n;;\n".encode("utf-8"),
            content_type="text/csv",
        )

        rows = read_import_rows(uploaded, ";")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["concepto"], "Hosting")
        self.assertEqual(rows[0]["monto"], "125000,50")

    def test_import_validation_rejects_missing_tenant_relations(self):
        batch = ImportBatch.objects.create(
            business=self.business,
            file_name="movimientos.xlsx",
            target_model=ImportBatch.FINANCIAL_ENTRY,
            total_rows=1,
        )
        record = ImportedRecord.objects.create(batch=batch, row_data={
            "concept": "Compra",
            "amount": "1000",
            "entry_type": FinancialEntry.EXPENSE,
            "entry_date": "2026-10-23",
            "currency": "COP",
            "category": "Categoría inexistente",
        })

        preview_batch(batch)
        record.refresh_from_db()

        self.assertEqual(record.status, ImportedRecord.INVALID)
        self.assertTrue(any("no existe" in error for error in record.validation_errors))

    def test_generic_import_templates_compile(self):
        for template_name in (
            "tenant/generic_import_upload.html",
            "tenant/generic_import_preview.html",
            "tenant/generic_import_batch_list.html",
            "tenant/generic_import_batch_detail.html",
        ):
            self.assertIsNotNone(get_template(template_name))

    def test_public_landing_is_informative_without_sample_customer_data(self):
        response = APIClient(HTTP_HOST=self.domain.domain).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tu negocio, con las cuentas")
        self.assertContains(response, "Finanzas y cartera")
        self.assertContains(response, "Facturas y cotizaciones")
        self.assertContains(response, "Vista ilustrativa")
        self.assertNotContains(response, "Public master online")
        self.assertNotContains(response, "Venta diaria sucursal norte")
        self.assertNotContains(response, "Tenant de pruebas")

    def test_authenticated_tenant_user_returns_to_dashboard_from_landing(self):
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(get_user_model().objects.create_user(username="home-user"))

        response = client.get("/")

        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)

    def test_tenant_dashboard_renders_for_business_and_individual_tenants(self):
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(
            get_user_model().objects.create_user(username="dashboard-user")
        )

        business_response = client.get("/dashboard/")
        self.assertEqual(business_response.status_code, 200)
        self.assertContains(business_response, "Tu empresa, en perspectiva")
        self.assertContains(business_response, "Ingresos y egresos del mes")
        self.assertContains(business_response, 'id="theme-toggle"')
        self.assertContains(business_response, 'class="skip-link"')

        self.tenant.tenant_type = "individual"
        self.tenant.save(update_fields=("tenant_type",))
        individual_response = client.get("/dashboard/")
        self.assertEqual(individual_response.status_code, 200)
        self.assertContains(individual_response, "Panel financiero personal")
        self.assertNotContains(individual_response, "Crear empleado")

    def test_platform_tenant_form_persists_service_follow_up_fields(self):
        form = PlatformTenantEditForm(
            instance=self.tenant,
            data={
                "name": self.tenant.name,
                "domain": self.domain.domain,
                "is_active": "on",
                "enabled_modules": ["finances"],
                "service_plan": "Profesional",
                "service_status": Tenant.SERVICE_PAST_DUE,
                "renewal_date": "2026-11-23",
                "platform_notes": "Contactar para revisar renovación.",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        updated_tenant = form.save()

        self.assertEqual(updated_tenant.service_plan, "Profesional")
        self.assertEqual(updated_tenant.service_status, Tenant.SERVICE_PAST_DUE)
        self.assertEqual(updated_tenant.renewal_date.isoformat(), "2026-11-23")
        self.assertEqual(
            updated_tenant.platform_notes, "Contactar para revisar renovación."
        )

    def test_suspended_service_status_disables_tenant_access(self):
        form = PlatformTenantEditForm(
            instance=self.tenant,
            data={
                "name": self.tenant.name,
                "domain": self.domain.domain,
                "is_active": "on",
                "enabled_modules": ["finances"],
                "service_plan": "Profesional",
                "service_status": Tenant.SERVICE_SUSPENDED,
                "renewal_date": "",
                "platform_notes": "",
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        response = APIClient(HTTP_HOST=self.domain.domain).get("/dashboard/")

        self.assertFalse(self.tenant.__class__.objects.get(pk=self.tenant.pk).is_active)
        self.assertEqual(response.status_code, 403)

    def test_platform_tenant_detail_template_compiles(self):
        self.assertIsNotNone(get_template("platform/tenant_detail.html"))

    def test_suspended_tenant_blocks_access_with_a_clear_message(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=("is_active",))

        response = APIClient(HTTP_HOST=self.domain.domain).get("/dashboard/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response, "Este espacio no está disponible", status_code=403
        )

    def test_health_check_reports_database_connectivity(self):
        response = APIClient(HTTP_HOST=self.domain.domain).get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


    def test_api_financial_entry_create_is_idempotent_and_audited(self):
        user = get_user_model().objects.create_user(username="api-finance-user")
        user.groups.add(Group.objects.create(name="Operador financiero"))
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_authenticate(user)
        payload = {
            "business": self.business.pk,
            "entry_type": FinancialEntry.INCOME,
            "concept": "Venta API",
            "amount": "125000.00",
            "currency": "COP",
            "entry_date": "2026-10-23",
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "venta-api-001"}

        first = client.post("/api/v1/financial-entries/", payload, format="json", **headers)
        replay = client.post("/api/v1/financial-entries/", payload, format="json", **headers)
        conflict = client.post(
            "/api/v1/financial-entries/",
            {**payload, "amount": "130000.00"},
            format="json",
            **headers,
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(FinancialEntry.objects.count(), 1)
        self.assertTrue(
            AuditEvent.objects.filter(
                entity="financial_entry",
                entity_id=str(first.data["id"]),
                actor=user,
            ).exists()
        )

    def test_api_webhook_endpoints_hide_secret_and_record_dispatch(self):
        self.tenant.enabled_modules.append("audit")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="api-webhook-user")
        user.groups.add(Group.objects.create(name="Administrador de empresa"))
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_authenticate(user)
        response = client.post(
            "/api/v1/webhooks/",
            {
                "name": "ERP externo",
                "url": "https://hooks.example.com/systemmanager",
                "secret": "secret-for-signing",
                "event_types": ["financial_entry.created"],
                "is_active": True,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="webhook-api-001",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("secret", response.data)
        endpoint = WebhookEndpoint.objects.get(pk=response.data["id"])
        with (
            patch(
                "businessmanagement.services.webhooks.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ),
            patch("businessmanagement.tasks.deliver_webhook.delay") as enqueue,
        ):
            from businessmanagement.services.webhooks import dispatch_webhook_event

            dispatch_webhook_event(
                "financial_entry.created",
                {"id": 42, "concept": "Venta"},
            )

        delivery = WebhookDelivery.objects.get(endpoint=endpoint)
        self.assertEqual(delivery.status, WebhookDelivery.PENDING)
        self.assertEqual(delivery.payload["id"], 42)
        enqueue.assert_called_once_with(delivery.pk, self.tenant.schema_name)

    def test_webhook_delivery_is_signed_and_records_success(self):
        endpoint = WebhookEndpoint.objects.create(
            name="ERP de prueba",
            url="https://hooks.example.com/events",
            secret="signing-secret",
            event_types=["payment.registered"],
        )
        payload = {"payment_id": 17, "amount": "25000.00"}
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event="payment.registered",
            target_url=endpoint.url,
            payload=payload,
        )
        response = Mock(status_code=204, text="accepted")

        with (
            patch("businessmanagement.tasks._ensure_public_webhook_destination"),
            patch("businessmanagement.tasks.requests.post", return_value=response) as post,
            schema_context("public"),
        ):
            result = deliver_webhook.run(delivery.pk, self.tenant.schema_name)

        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        expected_signature = hmac.new(
            b"signing-secret", body, hashlib.sha256
        ).hexdigest()
        self.assertEqual(result, WebhookDelivery.DELIVERED)
        self.assertEqual(post.call_args.kwargs["data"], body)
        self.assertEqual(
            post.call_args.kwargs["headers"]["X-SystemManager-Signature"],
            f"sha256={expected_signature}",
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.DELIVERED)
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.response_status, 204)

    def test_webhook_delivery_rejects_private_network_addresses(self):
        from businessmanagement.tasks import _ensure_public_webhook_destination

        with self.assertRaises(ValueError):
            _ensure_public_webhook_destination("https://10.0.0.2/private")

    def test_model_signals_publish_required_webhook_events(self):
        with patch("tenantdata.signals.dispatch_webhook_event") as dispatch:
            entry = FinancialEntry.objects.create(
                business=self.business,
                entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
                concept="Cuenta por cobrar",
                amount=Decimal("50000.00"),
                currency="COP",
                entry_date=date(2026, 10, 23),
            )
            invoice = Invoice.objects.create(
                business=self.business,
                issue_date=date(2026, 10, 23),
                total=Decimal("50000.00"),
            )
            invoice.status = Invoice.PAID
            invoice.save(update_fields=("status",))
            Payment.objects.create(
                financial_entry=entry,
                payment_date=date(2026, 10, 23),
                amount=Decimal("50000.00"),
                currency="COP",
            )

        self.assertEqual(
            [call.args[0] for call in dispatch.call_args_list],
            [
                "financial_entry.created",
                "invoice.created",
                "invoice.paid",
                "payment.registered",
            ],
        )


    def test_forecast_multicurrency_converts_each_payment_on_its_date(self):
        entry = FinancialEntry.objects.create(business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE, status=FinancialEntry.PARTIAL,
            concept="Multimoneda", amount=1000000, currency="COP",
            entry_date=date(2026, 10, 1), due_date=date(2026, 11, 1))
        for day, rate in [(10, 4000), (11, 4200)]:
            CurrencyRate.objects.create(currency="USD", rate_date=date(2026, 10, day), rate_to_local=rate)
            Payment.objects.create(financial_entry=entry, payment_date=date(2026, 10, day), amount=100, currency="USD")
        rows = cashflow_forecast(self.business, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(rows[0]["incoming"], Decimal("180000"))
        self.assertFalse(rows[0]["warnings"])
        entry.entry_type = FinancialEntry.ACCOUNT_PAYABLE
        entry.save(update_fields=["entry_type"])
        self.assertEqual(cashflow_forecast(self.business, date(2026, 11, 1), date(2026, 11, 30))[0]["outgoing"], Decimal("180000"))

    def test_currency_conversion_handles_cop_and_cross_rates(self):
        from businessmanagement.services.currency import convert_amount
        day = date(2026, 10, 1)
        CurrencyRate.objects.create(currency="USD", rate_date=day, rate_to_local=4000)
        CurrencyRate.objects.create(currency="EUR", rate_date=day, rate_to_local=5000)
        self.assertEqual(convert_amount(Decimal(100), "EUR", "USD", day), Decimal(125))
        self.assertEqual(convert_amount(Decimal(4000), "COP", "USD", day), Decimal(1))
        self.assertEqual(convert_amount(Decimal(1), "USD", "COP", day), Decimal(4000))
        for bad in [0, -1]:
            CurrencyRate.objects.filter(currency="USD").update(rate_to_local=bad)
            with self.assertRaises(ValueError): convert_amount(Decimal(1), "COP", "USD", day)
        with self.assertRaises(ValueError): convert_amount(Decimal(1), "EUR", "COP", date(2026, 10, 2))

    def test_forecast_warns_instead_of_inventing_a_balance_without_rates(self):
        entry = FinancialEntry.objects.create(business=self.business,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE, status=FinancialEntry.PARTIAL,
            concept="Sin tasa", amount=1000, currency="COP",
            entry_date=date(2026, 10, 1), due_date=date(2026, 11, 1))
        Payment.objects.create(financial_entry=entry, payment_date=date(2026, 10, 1), amount=1, currency="USD")
        rows = cashflow_forecast(self.business, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(rows[0]["incoming"], 0)
        self.assertIn(str(entry.pk), rows[0]["warnings"][0])
        html = get_template("tenant/partials/forecast_table.html").render({"forecast_rows": rows})
        self.assertIn("Proyección incompleta", html)

    def test_rate_sync_preserves_manual_rates_and_is_idempotent(self):
        from businessmanagement.tasks import update_currency_rates
        from businessmanagement.services.exchange_rates import SOURCE
        day = date(2026, 10, 1)
        CurrencyRate.objects.create(currency="USD", rate_date=day, rate_to_local=3900, source="manual")
        with patch("businessmanagement.services.exchange_rates.fetch_reference_rates", return_value=(day, {"USD": Decimal(4000), "EUR": Decimal(5000)})) as fetch:
            update_currency_rates()
            update_currency_rates()
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(CurrencyRate.objects.get(currency="USD").rate_to_local, 3900)
        self.assertEqual(CurrencyRate.objects.get(currency="EUR").source, SOURCE)
        self.assertEqual(CurrencyRate.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(entity="currency_rate").count(), 1)
        self.assertFalse(CurrencyRate.objects.filter(currency="BINANCE").exists())

    def test_rate_sync_provider_failure_writes_nothing(self):
        import requests
        from businessmanagement.tasks import update_currency_rates
        with patch("businessmanagement.services.exchange_rates.fetch_reference_rates", side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout): update_currency_rates()
        self.assertFalse(CurrencyRate.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(entity="currency_rate").exists())

    def test_editing_an_automatic_rate_makes_it_manual(self):
        user = get_user_model().objects.create_superuser(username="rate-admin", email="admin@example.com", password=None)
        admin_group, _ = Group.objects.get_or_create(name="Administrador de empresa")
        user.groups.add(admin_group)
        self.tenant.enabled_modules.append("currency_rates")
        self.tenant.save(update_fields=["enabled_modules"])
        client = APIClient(HTTP_HOST=self.domain.domain)
        client.force_login(user)
        rate = CurrencyRate.objects.create(currency="USD", rate_date=date(2026, 10, 1), rate_to_local=4000, source="open.er-api.com")
        response = client.post(f"/currency-rates/{rate.pk}/edit/", {
            "currency": "USD", "rate_date": "2026-10-01", "rate_to_local": "4100", "source": "open.er-api.com"})
        self.assertEqual(response.status_code, 302)
        rate.refresh_from_db()
        self.assertEqual(rate.source, "manual")
        self.assertEqual(rate.rate_to_local, 4100)
        self.tenant.enabled_modules.remove("currency_rates")
        self.tenant.save(update_fields=["enabled_modules"])

    def test_rate_sync_continues_when_another_tenant_fails(self):
        from businessmanagement.tasks import update_currency_rates
        tenants = [Mock(schema_name="missing_schema"), self.tenant]
        with patch("businessmanagement.tasks.Tenant.objects.filter") as query, patch(
            "businessmanagement.services.exchange_rates.fetch_reference_rates",
            return_value=(date(2026, 10, 1), {"USD": Decimal(4000), "EUR": Decimal(5000)})), patch(
            "businessmanagement.tasks.logger.exception"):
            query.return_value.exclude.return_value = tenants
            # Force the broken tenant to fail without falling back to public's search_path.
            from django_tenants.utils import schema_context as real_context
            from contextlib import contextmanager
            @contextmanager
            def context(schema):
                if schema == "missing_schema": raise RuntimeError("tenant unavailable")
                with real_context(schema): yield
            with patch("businessmanagement.tasks.schema_context", context), self.assertRaises(RuntimeError):
                update_currency_rates()
        self.assertEqual(CurrencyRate.objects.count(), 2)
        query.assert_called_once_with(is_active=True)

    def test_debit_note_pdf_detail_and_access_controls(self):
        self.client = APIClient(HTTP_HOST=self.domain.domain)
        self.tenant.enabled_modules.append("debit_notes")
        self.tenant.save(update_fields=["enabled_modules"])
        user = get_user_model().objects.create_user(username="note-reader")
        note = DebitNote.objects.create(business=self.business, issue_date=date(2026, 10, 1),
            description="Ajuste <contable> & otros", subtotal=100, tax_amount=19, retention_amount=2, total=117)
        DebitNoteItem.objects.create(debit_note=note, description="Servicio <A> & B " * 10,
            quantity=1, unit_price=100, subtotal=100)
        url = f"/debit-notes/{note.pk}/pdf/"
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(user)
        self.assertContains(self.client.get("/debit-notes/"), url)
        detail = self.client.get(f"/debit-notes/{note.pk}/")
        self.assertContains(detail, url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(note.debit_note_number, response["Content-Disposition"])
        pdf = b"".join(response.streaming_content)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"/Type /Page", pdf)
        self.assertTrue(AuditEvent.objects.filter(entity="debit_note", action=AuditEvent.ACCESS).exists())
        self.assertEqual(self.client.get("/debit-notes/999999/pdf/").status_code, 404)
        self.tenant.enabled_modules.remove("debit_notes")
        self.tenant.save(update_fields=["enabled_modules"])
        self.assertNotEqual(self.client.get(url).status_code, 200)


class ProductionHealthTests(TestCase):
    @override_settings(ALLOWED_HOSTS=["127.0.0.1"], SECURE_SSL_REDIRECT=True,
                       SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_health_does_not_require_a_provisioned_tenant(self):
        response = self.client.get("/health/", HTTP_HOST="127.0.0.1",
                                   HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @override_settings(ALLOWED_HOSTS=["127.0.0.1"], SECURE_SSL_REDIRECT=True)
    def test_health_keeps_https_redirect(self):
        response = self.client.get("/health/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 301)

    @override_settings(ALLOWED_HOSTS=["127.0.0.1"])
    def test_health_rejects_unknown_host(self):
        self.assertEqual(self.client.get("/health/", HTTP_HOST="unknown.invalid").status_code, 400)

    @override_settings(ALLOWED_HOSTS=["127.0.0.1"])
    def test_health_reports_a_failed_database_query(self):
        from django.db import OperationalError
        with patch("businessmanagement.health.connection.cursor", side_effect=OperationalError("unavailable")):
            response = self.client.get("/health/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


class ExchangeProviderTests(SimpleTestCase):
    def payload(self):
        from django.utils import timezone
        return {"result": "success", "base_code": "USD", "time_last_update_unix": timezone.now().timestamp(),
                "rates": {"COP": 4000, "EUR": .8}}

    def test_feed_converts_usd_based_rates_to_cop(self):
        from businessmanagement.services.exchange_rates import fetch_reference_rates
        with patch("businessmanagement.services.exchange_rates.requests.get", return_value=Mock(status_code=200, json=Mock(return_value=self.payload()))) as request:
            day, rates = fetch_reference_rates()
        self.assertEqual(rates, {"USD": Decimal("4000.0000"), "EUR": Decimal("5000.0000")})
        request.assert_called_once_with("https://open.er-api.com/v6/latest/USD", timeout=(5, 20), allow_redirects=False)

    def test_feed_rejects_malformed_stale_future_and_nonpositive_values(self):
        from businessmanagement.services.exchange_rates import fetch_reference_rates
        payloads = [[], {}, {**self.payload(), "result": "error"}, {**self.payload(), "base_code": "EUR"},
                    {**self.payload(), "time_last_update_unix": 0},
                    {**self.payload(), "time_last_update_unix": self.payload()["time_last_update_unix"] + 86400}]
        for value in [0, -1, "NaN", "Infinity", "1e99", None]:
            payloads.append({**self.payload(), "rates": {"COP": value, "EUR": .8}})
        for payload in payloads:
            with self.subTest(payload=payload), patch("businessmanagement.services.exchange_rates.requests.get", return_value=Mock(status_code=200, json=Mock(return_value=payload))):
                with self.assertRaises(ValueError): fetch_reference_rates()

    def test_feed_rejects_redirect_and_network_failure(self):
        import requests
        from businessmanagement.services.exchange_rates import fetch_reference_rates
        with patch("businessmanagement.services.exchange_rates.requests.get", return_value=Mock(status_code=302)):
            with self.assertRaises(ValueError): fetch_reference_rates()
        with patch("businessmanagement.services.exchange_rates.requests.get", side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout): fetch_reference_rates()
