from django.conf import settings
from django.db import models


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
    invoice_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )  # e.g., 19 for 19% IVA
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
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

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            import uuid

            self.invoice_number = f"REC-{str(uuid.uuid4())[:8].upper()}"
        super().save(*args, **kwargs)

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = (subtotal * self.tax_percentage) / 100
        self.total = subtotal + self.tax_amount
        return self.total


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

    STATUS_CHOICES = (
        (DRAFT, "Borrador"),
        (ACCEPTED, "Aceptada"),
        (CONVERTED, "Convertida"),
        (CANCELLED, "Cancelada"),
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

    quote_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)

    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
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

    def save(self, *args, **kwargs):
        if not self.quote_number:
            import uuid
            self.quote_number = f"REC-{str(uuid.uuid4())[:8].upper()}"
        super().save(*args, **kwargs)

    def calculate_totals(self, subtotal):
        self.subtotal = subtotal
        self.tax_amount = (subtotal * self.tax_percentage) / 100
        self.total = subtotal + self.tax_amount
        return self.total


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
    
         