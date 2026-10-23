from decimal import Decimal
import re

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename
from uuid import uuid4


class Business(models.Model):
    name_business_owner = models.CharField(max_length=255)
    last_name_business_owner = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255)
    business_phone = models.CharField(max_length=20)
    business_email = models.EmailField()
    business_address = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.business_name


class Employee(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    position = models.CharField(max_length=255)
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="employees"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class ThirdParty(models.Model):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    BOTH = "both"

    TYPE_CHOICES = (
        (CUSTOMER, "Cliente"),
        (SUPPLIER, "Proveedor"),
        (BOTH, "Cliente y proveedor"),
    )

    name = models.CharField(max_length=255)
    identification = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    third_party_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=CUSTOMER
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Tercero"
        verbose_name_plural = "Terceros"

    def __str__(self):
        return self.name


class Project(models.Model):
    COMPANY = "company"
    CLIENT = "client"
    PERSONAL = "personal"
    OTHER = "other"

    PROJECT_TYPE_CHOICES = (
        (COMPANY, "Proyecto interno de empresa"),
        (CLIENT, "Proyecto para cliente / obra"),
        (PERSONAL, "Proyecto de gastos personales"),
        (OTHER, "Otro"),
    )

    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"

    STATUS_CHOICES = (
        (ACTIVE, "Activo"),
        (COMPLETED, "Completado"),
        (ARCHIVED, "Archivado"),
    )

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    project_type = models.CharField(
        max_length=20, choices=PROJECT_TYPE_CHOICES, default=COMPANY
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    third_party = models.ForeignKey(
        ThirdParty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_owned",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"

    def __str__(self):
        return self.name


class Account(models.Model):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"
    COST = "cost"
    TYPE_CHOICES = (
        (ASSET, "Activo"),
        (LIABILITY, "Pasivo"),
        (EQUITY, "Patrimonio"),
        (INCOME, "Ingresos"),
        (EXPENSE, "Gastos"),
        (COST, "Costos"),
    )
    DEBIT = "debit"
    CREDIT = "credit"
    NATURE_CHOICES = ((DEBIT, "Débito"), (CREDIT, "Crédito"))

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=180)
    account_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    nature = models.CharField(max_length=10, choices=NATURE_CHOICES)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    accepts_entries = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)
        constraints = [models.UniqueConstraint(fields=("business", "code"), name="unique_account_code_per_business")]
        indexes = [models.Index(fields=("account_type", "is_active"))]
        verbose_name = "Cuenta contable"
        verbose_name_plural = "Plan contable"

    def clean(self):
        self.code = (self.code or "").strip()
        if not self.code.isdigit():
            raise ValidationError({"code": "El código contable debe contener únicamente números."})
        if self.parent:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError({"parent": "Una cuenta no puede ser su propio padre."})
            if self.parent.business_id != self.business_id:
                raise ValidationError({"parent": "La cuenta padre debe pertenecer a la misma empresa."})
            if not self.code.startswith(self.parent.code) or len(self.code) <= len(self.parent.code):
                raise ValidationError({"code": "El código debe extender el código de la cuenta padre."})
            if self.parent.accepts_entries:
                raise ValidationError({"parent": "La cuenta padre debe estar marcada como agrupadora."})

    @property
    def depth(self):
        return max(len(self.code) - 1, 0)

    def __str__(self):
        return f"{self.code} - {self.name}"


class FinancialCategory(models.Model):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"

    CATEGORY_TYPE_CHOICES = (
        (INCOME, "Ingreso"),
        (EXPENSE, "Egreso"),
        (TRANSFER, "Transferencia"),
    )

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="financial_categories"
    )
    name = models.CharField(max_length=120)
    category_type = models.CharField(max_length=20, choices=CATEGORY_TYPE_CHOICES)
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="financial_categories")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Categoría financiera"
        verbose_name_plural = "Categorías financieras"

    def __str__(self):
        return f"{self.name} ({self.get_category_type_display()})"


class CurrencyRate(models.Model):
    USD = "USD"
    EUR = "EUR"
    BINANCE = "BINANCE"

    CURRENCY_CHOICES = (
        (USD, "Dolar"),
        (EUR, "Euro"),
        (BINANCE, "Binance P2P"),
    )

    currency = models.CharField(max_length=12, choices=CURRENCY_CHOICES)
    rate_date = models.DateField()
    rate_to_local = models.DecimalField(max_digits=14, decimal_places=4)
    source = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-rate_date", "currency")
        constraints = [
            models.UniqueConstraint(
                fields=("currency", "rate_date"), name="unique_currency_rate_per_day"
            ),
        ]
        verbose_name = "Tasa de cambio"
        verbose_name_plural = "Tasas de cambio"

    def __str__(self):
        return f"{self.currency} {self.rate_date}: {self.rate_to_local}"


class TaxRule(models.Model):
    IVA = "IVA"
    RETENCION_FUENTE = "RETENCION_FUENTE"
    RETENCION_ICA = "RETENCION_ICA"
    OTRO = "OTRO"

    RULE_TYPE_CHOICES = (
        (IVA, "IVA"),
        (RETENCION_FUENTE, "Retención en la Fuente"),
        (RETENCION_ICA, "Retención ICA"),
        (OTRO, "Otro Impuesto/Retención"),
    )

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="tax_rules")
    name = models.CharField(max_length=120)
    rule_type = models.CharField(max_length=50, choices=RULE_TYPE_CHOICES)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)  # e.g., 19 for 19% IVA, 2.5 for 2.5% Retefuente
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Regla Tributaria"
        verbose_name_plural = "Reglas Tributarias"
        unique_together = ("business", "name", "rule_type")

    def __str__(self):
        return f"{self.name} ({self.percentage}%)"


class FinancialEntry(models.Model):
    INCOME = "income"
    EXPENSE = "expense"
    ACCOUNT_RECEIVABLE = "account_receivable"
    ACCOUNT_PAYABLE = "account_payable"

    ENTRY_TYPE_CHOICES = (
        (INCOME, "Ingreso/Venta"),
        (EXPENSE, "Egreso/Gasto"),
        (ACCOUNT_RECEIVABLE, "Cuenta por cobrar"),
        (ACCOUNT_PAYABLE, "Cuenta por pagar"),
    )

    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (PENDING, "Pendiente"),
        (PARTIAL, "Abono parcial"),
        (PAID, "Pagado"),
        (CANCELLED, "Cancelado"),
    )

    CURRENCY_CHOICES = (
        ("COP", "COP"),
        ("USD", "USD"),
        ("EUR", "EUR"),
        ("BINANCE", "Binance P2P"),
    )

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="financial_entries"
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
    )
    category = models.ForeignKey(
        FinancialCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
    )
    third_party = models.ForeignKey(
        ThirdParty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
    )
    entry_type = models.CharField(max_length=24, choices=ENTRY_TYPE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    concept = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=12, choices=CURRENCY_CHOICES, default="COP")
    entry_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to="financial_attachments/", blank=True, null=True
    )
    personal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-entry_date", "-created_at")
        indexes = [
            models.Index(fields=("entry_type", "status")),
            models.Index(fields=("entry_date", "currency")),
        ]
        verbose_name = "Movimiento financiero"
        verbose_name_plural = "Movimientos financieros"

    def __str__(self):
        return f"{self.get_entry_type_display()} - {self.concept}"


class AuditEvent(models.Model):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACCESS = "access"

    ACTION_CHOICES = (
        (CREATE, "Creacion"),
        (UPDATE, "Actualizacion"),
        (DELETE, "Eliminacion"),
        (ACCESS, "Acceso"),
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    entity = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("entity", "action")),
            models.Index(fields=("created_at",)),
        ]
        verbose_name = "Evento de auditoria"
        verbose_name_plural = "Eventos de auditoria"

    def __str__(self):
        return f"{self.get_action_display()} {self.entity}: {self.summary}"


class Invoice(models.Model):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"

    STATUS_CHOICES = (
        (DRAFT, "Borrador"),
        (ISSUED, "Emitida"),
        (PAID, "Pagada"),
        (OVERDUE, "Vencida"),
        (CANCELLED, "Cancelada"),
    )

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="invoices"
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    third_party = models.ForeignKey(
        ThirdParty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    invoice_number = models.CharField(max_length=50, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retention_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP"
    )
    notes = models.TextField(blank=True)
    financial_entry = models.OneToOneField(
        FinancialEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tax_rules = models.ManyToManyField(TaxRule, blank=True, related_name="invoices")

    class Meta:
        ordering = ("-issue_date", "-created_at")
        indexes = [
            models.Index(fields=("status", "due_date")),
            models.Index(fields=("business", "status")),
        ]
        verbose_name = "Factura"
        verbose_name_plural = "Facturas"

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.get_status_display()}"

    def generate_next_invoice_number(self):
        prefix = "FAC-"
        last_invoice = Invoice.objects.filter(business=self.business, invoice_number__startswith=prefix).order_by("-created_at").first()
        if last_invoice:
            match = re.search(r'\d+$', last_invoice.invoice_number)
            last_number = int(match.group(0)) if match else 0
            next_number = last_number + 1
            return f"{prefix}{next_number:06d}"
        return f"{prefix}000001"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.generate_next_invoice_number()
        super().save(*args, **kwargs)

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = Decimal("0.00")
        self.retention_amount = Decimal("0.00")
        for rule in self.tax_rules.all():
            if rule.rule_type == TaxRule.IVA:
                self.tax_amount += (subtotal * rule.percentage) / 100
            elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
                self.retention_amount += (subtotal * rule.percentage) / 100
        self.total = subtotal + self.tax_amount - self.retention_amount


class Payment(models.Model):
    financial_entry = models.ForeignKey(
        "FinancialEntry",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=12, choices=FinancialEntry.CURRENCY_CHOICES)
    concept = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-payment_date", "-created_at")
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        indexes = [
            models.Index(fields=("payment_date", "currency")),
            models.Index(fields=("financial_entry", "payment_date")),
        ]

    def __str__(self):
        return f"Pago {self.amount} {self.currency} ({self.financial_entry_id})"


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Factura"
        verbose_name_plural = "Items de Factura"

    def __str__(self):
        return f"{self.description} (x{self.quantity})"


class Quote(models.Model):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    CONVERTED = "converted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    STATUS_CHOICES = (
        (DRAFT, "Borrador"),
        (ACCEPTED, "Aceptada"),
        (CONVERTED, "Convertida"),
        (CANCELLED, "Cancelada"),
        (EXPIRED, "Vencida"),
    )

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="quotes"
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes",
    )
    third_party = models.ForeignKey(
        ThirdParty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes",
    )

    quote_number = models.CharField(max_length=50, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retention_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP"
    )

    notes = models.TextField(blank=True)

    converted_invoice = models.OneToOneField(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="converted_quote",
    )
    financial_entry = models.OneToOneField(
        FinancialEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tax_rules = models.ManyToManyField(TaxRule, blank=True, related_name="quotes")

    class Meta:
        ordering = ("-issue_date", "-created_at")
        indexes = [
            models.Index(fields=("status", "due_date")),
            models.Index(fields=("business", "status")),
        ]
        verbose_name = "Cotización"
        verbose_name_plural = "Cotizaciones"

    def __str__(self):
        return f"Quote {self.quote_number} - {self.get_status_display()}"

    def generate_next_quote_number(self):
        prefix = "QUO-"
        last_quote = Quote.objects.filter(business=self.business, quote_number__startswith=prefix).order_by("-created_at").first()
        if last_quote:
            match = re.search(r'\d+$', last_quote.quote_number)
            last_number = int(match.group(0)) if match else 0
            next_number = last_number + 1
            return f"{prefix}{next_number:06d}"
        return f"{prefix}000001"

    def save(self, *args, **kwargs):
        if not self.quote_number:
            self.quote_number = self.generate_next_quote_number()
        super().save(*args, **kwargs)

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = Decimal("0.00")
        self.retention_amount = Decimal("0.00")
        for rule in self.tax_rules.all():
            if rule.rule_type == TaxRule.IVA:
                self.tax_amount += (subtotal * rule.percentage) / 100
            elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
                self.retention_amount += (subtotal * rule.percentage) / 100
        self.total = subtotal + self.tax_amount - self.retention_amount


class QuoteItem(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Cotización"
        verbose_name_plural = "Items de Cotización"

    def __str__(self):
        return f"{self.description} (x{self.quantity})"


class BankAccount(models.Model):
    name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255, blank=True)
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="bank_accounts"
    )
    # Para MVP permitimos “moneda base” de la cuenta (el statement puede traer otras monedas).
    base_currency = models.CharField(
        max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Cuenta bancaria"
        verbose_name_plural = "Cuentas bancarias"

    def __str__(self):
        return f"{self.name} ({self.bank_name})" if self.bank_name else self.name




class BankStatement(models.Model):
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statements"
    )
    statement_date_from = models.DateField(null=True, blank=True)
    statement_date_to = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=120, blank=True)
    # CSV/PDF importado
    imported_file = models.FileField(
        upload_to="bank_statements/", blank=True, null=True
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_statements_created",
    )

    class Meta:
        ordering = ("-imported_at",)
        verbose_name = "Extracto bancario"
        verbose_name_plural = "Extractos bancarios"

    def __str__(self):
        return f"Statement {self.pk} - {self.bank_account_id}"


class BankTransaction(models.Model):
    IMPORTED = "imported"
    SUGGESTED = "suggested"
    RECONCILED = "reconciled"
    REJECTED = "rejected"

    STATUS_CHOICES = (
        (IMPORTED, "Importada"),
        (SUGGESTED, "Sugerida"),
        (RECONCILED, "Conciliada"),
        (REJECTED, "Rechazada"),
    )

    statement = models.ForeignKey(
        BankStatement, on_delete=models.CASCADE, related_name="transactions"
    )
    transaction_date = models.DateField()
    # descripción “limpia”
    description = models.CharField(max_length=255, blank=True)
    # campo de ayuda para matching (copia normalizada del concepto)
    concept = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(
        max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP"
    )
    external_id = models.CharField(max_length=120, blank=True)
    # para clasificar flujos
    direction = models.CharField(
        max_length=10,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=IMPORTED
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-transaction_date", "-created_at")
        indexes = [
            models.Index(fields=("transaction_date", "currency")),
            models.Index(fields=("amount", "currency")),
            models.Index(fields=("external_id",)),
        ]
        verbose_name = "Transacción bancaria"
        verbose_name_plural = "Transacciones bancarias"

    def __str__(self):
        return f"{self.transaction_date} - {self.amount} {self.currency}"


class Reconciliation(models.Model):
    # MVP: conciliación manual/automática sugerida, basada en match contra Payment.
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AUTO_MATCHED = "auto_matched"

    STATUS_CHOICES = (
        (PROPOSED, "Propuesta"),
        (CONFIRMED, "Confirmada"),
        (REJECTED, "Rechazada"),
        (AUTO_MATCHED, "Auto-matcheada"),
    )

    reconciliation_type = models.CharField(max_length=20, default="manual")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PROPOSED)
    match_confidence = models.PositiveIntegerField(default=0)

    bank_transaction = models.ForeignKey(
        BankTransaction, on_delete=models.CASCADE, related_name="reconciliations"
    )
    # Para el MVP usamos Payment como fuente principal.
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        related_name="reconciliations",
        null=True,
        blank=True,
    )
    financial_entry = models.ForeignKey(
        FinancialEntry,
        on_delete=models.SET_NULL,
        related_name="reconciliations",
        null=True,
        blank=True,
    )

    matched_at = models.DateTimeField(null=True, blank=True)
    matched_concept = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Conciliación"
        verbose_name_plural = "Conciliaciones"
        indexes = [
            models.Index(fields=("status", "match_confidence")),
            models.Index(fields=("bank_transaction",)),
        ]
        # Evitar duplicar confirmaciones para la misma transaction.
        constraints = [
            models.UniqueConstraint(
                fields=("bank_transaction", "status"),
                name="unique_bank_transaction_per_status",
            )
        ]

    def __str__(self):
        return f"Reconciliation {self.bank_transaction_id} - {self.status}"


class CreditNote(models.Model):
    DRAFT = "draft"
    ISSUED = "issued"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Borrador"),
        (ISSUED, "Emitida"),
        (CANCELLED, "Anulada"),
    ]

    credit_note_number = models.CharField(max_length=100, unique=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_notes")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="credit_notes")
    third_party = models.ForeignKey(ThirdParty, on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_notes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00")) # Refactor: calculate and return, don't save
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    retention_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP")
    description = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    financial_entry = models.OneToOneField(FinancialEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_note")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_credit_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tax_rules = models.ManyToManyField(TaxRule, blank=True, related_name="credit_notes")

    class Meta:
        unique_together = ("business", "credit_note_number")
        ordering = ["-issue_date", "-created_at"]

    def __str__(self):
        return f"Credit Note {self.credit_note_number} for {self.third_party.name if self.third_party else 'N/A'}"

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = Decimal("0.00")
        self.retention_amount = Decimal("0.00")
        for rule in self.tax_rules.all():
            if rule.rule_type == TaxRule.IVA:
                self.tax_amount += (subtotal * rule.percentage) / 100
            elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
                self.retention_amount += (subtotal * rule.percentage) / 100
        self.total = subtotal + self.tax_amount - self.retention_amount

    def save(self, *args, **kwargs):
        if not self.credit_note_number:
            prefix = "CN-"
            last_cn = CreditNote.objects.filter(business=self.business, credit_note_number__startswith=prefix).order_by("-created_at").first()
            if last_cn:
                match = re.search(r'\d+$', last_cn.credit_note_number)
                last_number = int(match.group(0)) if match else 0
                next_number = last_number + 1
                self.credit_note_number = f"{prefix}{next_number:06d}"
            else:
                self.credit_note_number = f"{prefix}000001"
        super().save(*args, **kwargs)


class CreditNoteItem(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Nota de Crédito"
        verbose_name_plural = "Items de Nota de Crédito"

    def __str__(self):
        return f"{self.description} ({self.quantity} x {self.unit_price})"


class DebitNote(models.Model):
    DRAFT = "draft"
    ISSUED = "issued"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Borrador"),
        (ISSUED, "Emitida"),
        (CANCELLED, "Anulada"),
    ]

    debit_note_number = models.CharField(max_length=100, unique=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="debit_notes")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="debit_notes")
    third_party = models.ForeignKey(ThirdParty, on_delete=models.SET_NULL, null=True, blank=True, related_name="debit_notes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00")) # Refactor: calculate and return, don't save
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    retention_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP")
    description = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    financial_entry = models.OneToOneField(FinancialEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name="debit_note")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_debit_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tax_rules = models.ManyToManyField(TaxRule, blank=True, related_name="debit_notes")

    class Meta:
        unique_together = ("business", "debit_note_number")
        ordering = ["-issue_date", "-created_at"]

    def __str__(self):
        return f"Debit Note {self.debit_note_number} for {self.third_party.name if self.third_party else 'N/A'}"

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = Decimal("0.00")
        self.retention_amount = Decimal("0.00")
        for rule in self.tax_rules.all():
            if rule.rule_type == TaxRule.IVA:
                self.tax_amount += (subtotal * rule.percentage) / 100
            elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
                self.retention_amount += (subtotal * rule.percentage) / 100
        self.total = subtotal + self.tax_amount - self.retention_amount

    def save(self, *args, **kwargs):
        if not self.debit_note_number:
            prefix = "DN-"
            last_dn = DebitNote.objects.filter(business=self.business, debit_note_number__startswith=prefix).order_by("-created_at").first()
            if last_dn:
                match = re.search(r'\d+$', last_dn.debit_note_number)
                last_number = int(match.group(0)) if match else 0
                next_number = last_number + 1
                self.debit_note_number = f"{prefix}{next_number:06d}"
            else:
                self.debit_note_number = f"{prefix}000001"
        super().save(*args, **kwargs)


class DebitNoteItem(models.Model):
    debit_note = models.ForeignKey(DebitNote, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Nota de Débito"
        verbose_name_plural = "Items de Nota de Débito"

    def __str__(self):
        return f"{self.description} ({self.quantity} x {self.unit_price})"


class ImportBatch(models.Model):
    FINANCIAL_ENTRY = 'financial_entry'
    THIRD_PARTY = 'third_party'
    TARGET_MODEL_CHOICES = [
        (FINANCIAL_ENTRY, 'Movimiento Financiero'),
        (THIRD_PARTY, 'Tercero'),
    ]
    UPLOADED = "uploaded"
    PREVIEWED = "previewed"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    STATUS_CHOICES = [
        (UPLOADED, "Subido"),
        (PREVIEWED, "Validado"),
        (CONFIRMED, "Confirmado"),
        (FAILED, "Fallido"),
        (ROLLED_BACK, "Revertido"),
    ]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='import_batches')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='import_batches_created')
    created_at = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=255)
    target_model = models.CharField(max_length=50, choices=TARGET_MODEL_CHOICES)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=UPLOADED)
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    notes = models.TextField(blank=True, null=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_batches_rolled_back")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lote de Importación"
        verbose_name_plural = "Lotes de Importación"

    def __str__(self):
        return f"Import Batch {self.pk} - {self.target_model} - {self.file_name}"

class ImportedRecord(models.Model):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    PROCESSED = "processed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    STATUS_CHOICES = [
        (PENDING, "Pendiente"),
        (VALID, "Válido"),
        (INVALID, "Inválido"),
        (PROCESSED, "Procesado"),
        (FAILED, "Fallido"),
        (ROLLED_BACK, "Revertido"),
    ]
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='records')
    row_data = models.JSONField() # Stores the raw data of the row
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=PENDING)
    validation_errors = models.JSONField(default=list, blank=True)
    processed_object_id = models.CharField(max_length=255, blank=True, null=True) # FK to FinancialEntry or ThirdParty
    processed_object_model = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Registro Importado"
        verbose_name_plural = "Registros Importados"

    def __str__(self):
        return f"Record {self.id} in Batch {self.batch.pk}"


class Budget(models.Model):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Borrador"),
        (ACTIVE, "Activo"),
        (COMPLETED, "Completado"),
        (CANCELLED, "Cancelado"),
    ]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="budgets")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    period_start_date = models.DateField()
    period_end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    total_budgeted_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_budgets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start_date", "name"]
        verbose_name = "Presupuesto"
        verbose_name_plural = "Presupuestos"
        unique_together = ("business", "name", "period_start_date", "period_end_date")

    def __str__(self):
        return f"{self.name} ({self.period_start_date} - {self.period_end_date})"

    def calculate_total_budgeted_amount(self):
        self.total_budgeted_amount = self.lines.aggregate(models.Sum('budgeted_amount'))['budgeted_amount__sum'] or Decimal("0.00")
        # self.save(update_fields=['total_budgeted_amount']) # Don't save here, let the view handle it


class BudgetLine(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    category = models.ForeignKey(FinancialCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="budget_lines")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="budget_lines")
    concept = models.CharField(max_length=255)
    budgeted_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=12, choices=FinancialEntry.CURRENCY_CHOICES, default="COP")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["concept"]
        verbose_name = "Línea de Presupuesto"
        verbose_name_plural = "Líneas de Presupuesto"

    def __str__(self):
        return f"{self.concept} ({self.budgeted_amount} {self.currency})"

    @property
    def actual_amount(self):
        # Calculate actual amount from FinancialEntry within the budget period
        # This is a simplified version. A more robust implementation would consider
        # entry_type (income/expense), specific categories/projects, and currencies.
        # For now, sum up expenses for the given category/project within the budget period
        filters = {'business': self.budget.business, 'entry_date__range': (self.budget.period_start_date, self.budget.period_end_date), 'currency': self.currency, 'status__in': [FinancialEntry.PAID, FinancialEntry.PARTIAL]}
        if self.category:
            filters['category'] = self.category
        if self.project:
            filters['project'] = self.project
        
        return FinancialEntry.objects.filter(entry_type=FinancialEntry.EXPENSE, **filters).aggregate(models.Sum('amount'))['amount__sum'] or Decimal("0.00")


class Notification(models.Model):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    LEVEL_CHOICES = (
        (INFO, "Información"),
        (SUCCESS, "Éxito"),
        (WARNING, "Advertencia"),
        (DANGER, "Crítica"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=INFO)
    title = models.CharField(max_length=160)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True)
    entity = models.CharField(max_length=80, blank=True)
    entity_id = models.CharField(max_length=80, blank=True)
    dedupe_key = models.CharField(max_length=190, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("recipient", "is_read", "created_at")),
            models.Index(fields=("entity", "entity_id")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "dedupe_key"),
                condition=~models.Q(dedupe_key=""),
                name="unique_notification_dedupe_per_recipient",
            )
        ]
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"

    def __str__(self):
        return f"{self.title} → {self.recipient}"


class ApprovalRequest(models.Model):
    QUOTE = "quote"
    EXPENSE = "expense"
    ENTITY_CHOICES = ((QUOTE, "Cotización"), (EXPENSE, "Gasto"))
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (PENDING, "Pendiente"),
        (APPROVED, "Aprobada"),
        (REJECTED, "Rechazada"),
        (CANCELLED, "Cancelada"),
    )

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="approval_requests")
    entity_type = models.CharField(max_length=30, choices=ENTITY_CHOICES)
    entity_id = models.PositiveBigIntegerField()
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    reason = models.TextField(blank=True)
    decision_notes = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="approval_requests_created")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approval_requests_reviewed")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        indexes = [models.Index(fields=("status", "entity_type", "requested_at"))]
        constraints = [
            models.UniqueConstraint(
                fields=("entity_type", "entity_id"),
                condition=models.Q(status="pending"),
                name="unique_pending_approval_per_entity",
            )
        ]
        verbose_name = "Solicitud de aprobación"
        verbose_name_plural = "Solicitudes de aprobación"

    def __str__(self):
        return f"{self.get_entity_type_display()}: {self.title} ({self.get_status_display()})"


def document_version_upload_to(instance, filename):
    """Store opaque names so user filenames cannot collide or leak in URLs."""
    safe_name = get_valid_filename(filename) or "documento"
    return f"documents/{instance.document_id}/{uuid4().hex}-{safe_name}"


class Document(models.Model):
    INVOICE = "invoice"
    QUOTE = "quote"
    CONTRACT = "contract"
    RECEIPT = "receipt"
    BANK = "bank"
    HR = "hr"
    OTHER = "other"
    TYPE_CHOICES = (
        (INVOICE, "Factura"),
        (QUOTE, "Cotización"),
        (CONTRACT, "Contrato"),
        (RECEIPT, "Soporte / recibo"),
        (BANK, "Documento bancario"),
        (HR, "Talento humano"),
        (OTHER, "Otro"),
    )
    ACTIVE = "active"
    ARCHIVED = "archived"
    STATUS_CHOICES = ((ACTIVE, "Activo"), (ARCHIVED, "Archivado"))

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=220)
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=OTHER)
    description = models.TextField(blank=True)
    tags = models.CharField(max_length=300, blank=True, help_text="Etiquetas separadas por comas")
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=ACTIVE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="documents_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [
            models.Index(fields=("business", "status", "document_type")),
            models.Index(fields=("entity_type", "entity_id")),
        ]
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"

    def __str__(self):
        return self.title

    @property
    def latest_version(self):
        return self.versions.order_by("-version").first()


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to=document_version_upload_to, max_length=500)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="document_versions_uploaded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(fields=("document", "version"), name="unique_document_version")
        ]
        verbose_name = "Versión documental"
        verbose_name_plural = "Versiones documentales"

    def __str__(self):
        return f"{self.document.title} v{self.version}"


class APIIdempotencyRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_idempotency_records",
    )
    key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "key"), name="unique_api_idempotency_key_per_user"
            )
        ]
        indexes = [
            models.Index(fields=("created_at",), name="api_idem_created_idx")
        ]
        verbose_name = "Registro de idempotencia API"
        verbose_name_plural = "Registros de idempotencia API"


class WebhookEndpoint(models.Model):
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    PAYMENT_REGISTERED = "payment.registered"
    FINANCIAL_ENTRY_CREATED = "financial_entry.created"
    EVENT_CHOICES = (
        (INVOICE_CREATED, "Factura creada"),
        (INVOICE_PAID, "Factura pagada"),
        (PAYMENT_REGISTERED, "Pago registrado"),
        (FINANCIAL_ENTRY_CREATED, "Movimiento financiero creado"),
    )

    name = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=128)
    event_types = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_endpoints_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        verbose_name = "Endpoint webhook"
        verbose_name_plural = "Endpoints webhook"

    def __str__(self):
        return self.name


class WebhookDelivery(models.Model):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    STATUS_CHOICES = (
        (PENDING, "Pendiente"),
        (DELIVERED, "Entregada"),
        (FAILED, "Fallida"),
    )

    endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    event = models.CharField(max_length=80)
    target_url = models.URLField(max_length=500)
    payload = models.JSONField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveIntegerField(default=0)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("status", "created_at"), name="webhook_status_date_idx"
            ),
            models.Index(fields=("event", "created_at"), name="webhook_event_date_idx"),
        ]
        verbose_name = "Entrega de webhook"
        verbose_name_plural = "Entregas de webhooks"
