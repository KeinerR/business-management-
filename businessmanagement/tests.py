from datetime import date
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase

from businessmanagement.forms import InvoiceForm, QuoteForm, TaxRuleForm
from businessmanagement.services.banking import _parse_csv_date
from tenantdata.models import Business, Invoice, Quote, TaxRule


class BusinessFlowTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de pruebas"
        tenant.enabled_modules = [
            "invoices",
            "quotes",
            "taxes",
            "banking",
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
