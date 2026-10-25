from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model # Import inlineformset_factory
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.forms import ModelChoiceField

from tenantdata.models import (
    Business,
    CurrencyRate,
    Employee,
    FinancialCategory,
    FinancialEntry,
    Invoice,
    InvoiceItem,
    Payment,
    Project,
    ThirdParty,
    CreditNote,
    CreditNoteItem,
    TaxRule,
    Budget,
    BudgetLine,
    ImportBatch,
    ImportedRecord,
    BankAccount,
    Quote,
    ApprovalRequest,
    Account,
    Document,
    DocumentTag,
    # Nota: DebitNote debe existir en tenantdata.models, pero si el import falla
    # (por dependencia circular en runtime) evitamos que el NameError derribe el worker.
    DebitNote,
    DebitNoteItem,
)
from django.forms import inlineformset_factory


from .models import Domain, Tenant
from .modules import AVAILABLE_MODULES, MODULES_INDIVIDUAL, MODULES_BUSINESS


def sync_tenant_service_state(cleaned_data):
    service_status = cleaned_data.get("service_status")
    is_active = cleaned_data.get("is_active")
    if service_status == Tenant.SERVICE_SUSPENDED:
        cleaned_data["is_active"] = False
    elif not is_active and service_status in (Tenant.SERVICE_ACTIVE, Tenant.SERVICE_TRIAL):
        cleaned_data["service_status"] = Tenant.SERVICE_SUSPENDED
    return cleaned_data


class TwoDecimalNumberInput(forms.NumberInput):
    def format_value(self, value):
        if value in (None, ""):
            return super().format_value(value)
        try:
            return format(value, ".2f")
        except (TypeError, ValueError):
            return super().format_value(value)


class PlatformTenantCreateForm(forms.ModelForm):
    domain = forms.CharField(
        label="Dominio",
        help_text="Ejemplo: empresa.127.0.0.1.nip.io, sin http ni puerto.",
    )
    name_business_owner = forms.CharField(
        label="Nombre del propietario", required=False
    )
    last_name_business_owner = forms.CharField(
        label="Apellido del propietario", required=False
    )
    business_name = forms.CharField(label="Nombre de la empresa", required=False)
    business_phone = forms.CharField(label="Telefono", required=False)
    business_email = forms.EmailField(label="Email de la empresa", required=False)
    business_address = forms.CharField(label="Direccion", required=False)
    description = forms.CharField(
        label="Descripcion", required=False, widget=forms.Textarea
    )
    admin_username = forms.CharField(label="Usuario administrador")
    admin_password = forms.CharField(label="Contrasena", widget=forms.PasswordInput)
    admin_first_name = forms.CharField(label="Nombre del usuario")
    admin_last_name = forms.CharField(label="Apellido del usuario")
    admin_email = forms.EmailField(label="Email del usuario")
    admin_phone = forms.CharField(label="Telefono del usuario")

    enabled_modules = forms.MultipleChoiceField(
        choices=AVAILABLE_MODULES,
        widget=forms.CheckboxSelectMultiple,
        label="Módulos Habilitados",
        initial=[m[0] for m in AVAILABLE_MODULES],
        required=False,
    )

    class Meta:
        model = Tenant
        fields = (
            "name",
            "schema_name",
            "tenant_type",
            "enabled_modules",
            "is_active",
            "service_plan",
            "service_status",
            "renewal_date",
            "platform_notes",
        )
        labels = {
            "name": "Nombre del tenant / Razón Social",
            "schema_name": "Schema",
            "tenant_type": "Tipo de Cuenta",
            "is_active": "Activo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ("enabled_modules", "is_active"):
                continue
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})

        self.fields["description"].widget.attrs.update({"rows": 3})
        self.fields["admin_password"].widget.attrs.update(
            {"autocomplete": "new-password"}
        )
        self.fields["renewal_date"].widget = forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        )
        self.fields["platform_notes"].widget.attrs.update(
            {"class": "form-control", "rows": 3}
        )

    def clean(self):
        cleaned_data = super().clean()
        tenant_type = cleaned_data.get("tenant_type")

        if tenant_type == Tenant.TYPE_BUSINESS:
            required_business_fields = [
                "name_business_owner",
                "last_name_business_owner",
                "business_name",
                "business_phone",
                "business_email",
                "business_address",
            ]
            for field in required_business_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, "Este campo es obligatorio para empresas.")
        else:
            if not cleaned_data.get("business_name"):
                cleaned_data["business_name"] = (
                    f"Perfil Personal: {cleaned_data.get('admin_first_name')} {cleaned_data.get('admin_last_name')}"
                )
            if not cleaned_data.get("name_business_owner"):
                cleaned_data["name_business_owner"] = cleaned_data.get(
                    "admin_first_name"
                )
            if not cleaned_data.get("last_name_business_owner"):
                cleaned_data["last_name_business_owner"] = cleaned_data.get(
                    "admin_last_name"
                )
            if not cleaned_data.get("business_email"):
                cleaned_data["business_email"] = cleaned_data.get("admin_email")
            if not cleaned_data.get("business_phone"):
                cleaned_data["business_phone"] = cleaned_data.get("admin_phone")
            if not cleaned_data.get("business_address"):
                cleaned_data["business_address"] = "Dirección Personal"

        return sync_tenant_service_state(cleaned_data)


class PlatformTenantEditForm(forms.ModelForm):
    domain = forms.CharField(
        label="Dominio",
        help_text="Ejemplo: empresa.127.0.0.1.nip.io, sin http ni puerto.",
    )

    enabled_modules = forms.MultipleChoiceField(
        choices=AVAILABLE_MODULES,
        widget=forms.CheckboxSelectMultiple,
        label="Módulos Habilitados",
        required=False,
    )

    class Meta:
        model = Tenant
        fields = (
            "name",
            "is_active",
            "enabled_modules",
            "service_plan",
            "service_status",
            "renewal_date",
            "platform_notes",
        )
        labels = {
            "name": "Nombre del tenant",
            "is_active": "Activo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            primary_domain = self.instance.domains.filter(is_primary=True).first()
            if primary_domain:
                self.fields["domain"].initial = primary_domain.domain

        for field_name, field in self.fields.items():
            if field_name in ("enabled_modules", "is_active"):
                continue
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})
        self.fields["renewal_date"].widget = forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        )
        self.fields["platform_notes"].widget.attrs.update(
            {"class": "form-control", "rows": 3}
        )

    def clean_domain(self):
        domain = self.cleaned_data["domain"].strip().lower()
        domain = domain.removeprefix("http://").removeprefix("https://").split("/")[0]
        domain = domain.split(":")[0]
        if Domain.objects.filter(domain=domain).exclude(tenant=self.instance).exists():
            raise forms.ValidationError("Ya existe un tenant con este dominio.")
        return domain

    def clean(self):
        return sync_tenant_service_state(super().clean())


class EmployeeCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)
    first_name = forms.CharField(max_length=255)
    last_name = forms.CharField(max_length=255)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)
    position = forms.CharField(max_length=255)
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        label="Grupos",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == "groups":
                continue
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})

        self.fields["username"].widget.attrs.update({"autocomplete": "username"})
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["groups"].queryset = Group.objects.order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Las contraseñas no coinciden.")

        username = cleaned_data.get("username")
        if username and get_user_model().objects.filter(username=username).exists():
            self.add_error("username", "Ya existe un usuario con ese nombre.")

        return cleaned_data


class EmployeeEditForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Grupos",
    )

    class Meta:
        model = Employee
        fields = ("first_name", "last_name", "email", "phone", "position", "groups")
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Email",
            "phone": "Telefono",
            "position": "Cargo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["groups"].initial = self.instance.user.groups.all()
        for field_name, field in self.fields.items():
            if field_name == "groups":
                continue
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})


class TenantUserForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Grupos",
    )

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email", "groups")
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Email",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == "groups":
                continue
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})


class TenantGroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").order_by(
            "content_type__app_label", "codename"
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Permisos",
    )

    class Meta:
        model = Group
        fields = ("name", "permissions")
        labels = {"name": "Nombre del grupo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "off"}
        )
        self.fields["permissions"].widget.attrs.update({"class": "form-check-input"})


class ThirdPartyForm(forms.ModelForm):
    class Meta:
        model = ThirdParty
        fields = (
            "name",
            "identification",
            "third_party_type",
            "email",
            "phone",
            "address",
            "is_active",
        )
        labels = {
            "name": "Nombre",
            "identification": "Identificacion",
            "third_party_type": "Tipo",
            "email": "Email",
            "phone": "Telefono",
            "address": "Direccion",
            "is_active": "Activo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update(
                    {"class": "form-control", "autocomplete": "off"}
                )


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ("name", "description", "period_start_date", "period_end_date", "status", "currency")
        labels = {
            "name": "Nombre del Presupuesto",
            "description": "Descripción",
            "period_start_date": "Fecha de Inicio",
            "period_end_date": "Fecha de Fin",
            "status": "Estado",
            "currency": "Moneda",
        }
        widgets = {
            "period_start_date": forms.DateInput(attrs={"type": "date"}),
            "period_end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start_date")
        end = cleaned.get("period_end_date")
        if start and end and end < start:
            self.add_error("period_end_date", "La fecha final no puede ser anterior a la inicial.")
        return cleaned


class BudgetLineForm(forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ("concept", "category", "project", "budgeted_amount", "currency")
        labels = {
            "concept": "Concepto",
            "category": "Categoría",
            "project": "Proyecto",
            "budgeted_amount": "Monto Presupuestado",
            "currency": "Moneda",
        }
        widgets = {
            "budgeted_amount": TwoDecimalNumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = FinancialCategory.objects.filter(is_active=True).order_by("name")
        self.fields["project"].queryset = Project.objects.all().order_by("name")
        self.fields["category"].required = False
        self.fields["project"].required = False
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})

    def clean_budgeted_amount(self):
        amount = self.cleaned_data["budgeted_amount"]
        if amount <= 0:
            raise ValidationError("El monto presupuestado debe ser mayor que cero.")
        return amount


BudgetLineFormSet = inlineformset_factory(
    Budget,
    BudgetLine,
    form=BudgetLineForm,
    extra=1, # Initial empty forms
    can_delete=True,
)


class GenericImportUploadForm(forms.Form):
    target_model = forms.ChoiceField(
        choices=ImportBatch.TARGET_MODEL_CHOICES,
        label="Modelo a importar",
        help_text="Seleccione el tipo de datos que desea importar."
    )
    file = forms.FileField(label="Archivo CSV o Excel", help_text="Suba su archivo de datos.")
    delimiter = forms.ChoiceField(
        choices=(
            (',', 'Coma (,)'),
            (';', 'Punto y coma (;)'),
            ('\t', 'Tabulación'),
        ),
        label="Separador de CSV (si es CSV)",
        initial=',',
        required=False,
        help_text="Solo aplica para archivos CSV."
    )
    has_header = forms.BooleanField(
        label="El archivo tiene encabezado",
        initial=True,
        required=False,
        help_text="Marque si la primera fila de su archivo contiene los nombres de las columnas."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == 'has_header':
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update({"class": "form-control"})

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = uploaded.name.lower().rsplit(".", 1)[-1] if "." in uploaded.name else ""
        if extension not in {"csv", "xlsx"}:
            raise ValidationError("Use un archivo CSV o Excel .xlsx.")
        if uploaded.size > 10 * 1024 * 1024:
            raise ValidationError("El archivo supera el máximo de 10 MB.")
        return uploaded

    def clean_has_header(self):
        if not self.cleaned_data.get("has_header"):
            raise ValidationError("La primera fila debe contener los nombres de las columnas.")
        return True




class FinancialEntryForm(forms.ModelForm):
    class Meta:
        model = FinancialEntry
        fields = (
            "entry_type",
            "status",
            "project",
            "category",
            "third_party",
            "concept",
            "amount",
            "currency",
            "entry_date",
            "due_date",
            "notes",
            "attachment",
            "personal",
        )
        labels = {
            "entry_type": "Tipo",
            "status": "Estado",
            "project": "Proyecto",
            "category": "Categoría",
            "third_party": "Tercero",
            "concept": "Concepto",
            "amount": "Monto",
            "currency": "Moneda",
            "entry_date": "Fecha",
            "due_date": "Vence",
            "notes": "Notas",
            "personal": "¿Es personal?",
        }
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant_type = kwargs.pop("tenant_type", Tenant.TYPE_BUSINESS)
        super().__init__(*args, **kwargs)
        self.fields["third_party"].queryset = ThirdParty.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["third_party"].required = False
        self.fields["project"].queryset = Project.objects.all().order_by("name")
        self.fields["category"].queryset = FinancialCategory.objects.filter(
            is_active=True
        ).order_by("name")

        if self.tenant_type == Tenant.TYPE_INDIVIDUAL:
            self.fields["personal"].initial = True
            self.fields["personal"].widget = forms.HiddenInput()
            self.fields["project"].required = False
            self.fields["category"].required = False

        for field_name, field in self.fields.items():
            if field_name == "personal":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update({"class": "form-control"})
            if field_name == "attachment":
                field.widget.attrs.update({"class": "form-control"})

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("El monto debe ser mayor que cero.")
        return amount


class CurrencyRateForm(forms.ModelForm):
    class Meta:
        model = CurrencyRate
        fields = ("currency", "rate_date", "rate_to_local", "source")
        labels = {
            "currency": "Moneda",
            "rate_date": "Fecha",
            "rate_to_local": "Tasa local",
            "source": "Fuente",
        }
        widgets = {
            "rate_date": forms.DateInput(attrs={"type": "date"}),
            "rate_to_local": TwoDecimalNumberInput(
                attrs={"step": "0.01", "inputmode": "decimal"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "name",
            "description",
            "project_type",
            "start_date",
            "end_date",
            "status",
            "third_party",
            "owner",
        )
        labels = {
            "name": "Nombre del proyecto",
            "description": "Descripción",
            "project_type": "Tipo de proyecto",
            "start_date": "Fecha inicio",
            "end_date": "Fecha fin",
            "status": "Estado",
            "third_party": "Tercero asociado",
            "owner": "Responsable",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "off"})


class FinancialCategoryForm(forms.ModelForm):
    class Meta:
        model = FinancialCategory
        fields = ("name", "category_type", "account", "is_active")
        labels = {
            "name": "Nombre de la categoría",
            "category_type": "Tipo",
            "account": "Cuenta contable",
            "is_active": "Activa",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(is_active=True, accepts_entries=True).order_by("code")
        self.fields["account"].required = False
        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update(
                    {"class": "form-control", "autocomplete": "off"}
                )


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ("code", "name", "account_type", "nature", "parent", "accepts_entries", "is_active", "description")
        labels = {
            "code": "Código PUC",
            "name": "Nombre",
            "account_type": "Tipo",
            "nature": "Naturaleza",
            "parent": "Cuenta padre",
            "accepts_entries": "Permite movimientos",
            "is_active": "Activa",
            "description": "Descripción",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        business = kwargs.pop("business")
        super().__init__(*args, **kwargs)
        self.instance.business = business
        self.fields["parent"].queryset = Account.objects.filter(
            business=business, accepts_entries=False, is_active=True
        ).exclude(pk=self.instance.pk).order_by("code")
        self.fields["parent"].required = False
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name in ("accepts_entries", "is_active") else "form-control"


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = (
            "invoice_number",
            "project",
            "third_party",
            "issue_date",
            "due_date",
            "currency",
            "description",
            "notes",
        )
        labels = {
            "invoice_number": "Número de factura",
            "project": "Proyecto",
            "third_party": "Cliente/Proveedor",
            "issue_date": "Fecha de emisión",
            "due_date": "Fecha de vencimiento",
            "currency": "Moneda",
            "description": "Descripción",
            "notes": "Notas",
        }
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant_type = kwargs.pop("tenant_type", Tenant.TYPE_BUSINESS)
        super().__init__(*args, **kwargs)
        self.fields["third_party"].queryset = ThirdParty.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["third_party"].required = False
        self.fields["project"].queryset = Project.objects.all().order_by("name")

        if self.tenant_type == Tenant.TYPE_INDIVIDUAL:
            self.fields["invoice_number"].required = False
            self.fields["invoice_number"].help_text = (
                "Opcional. Se generará uno automático si se deja vacío."
            )
            self.fields["project"].required = False

        for field_name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})

        self.fields["tax_rules"] = forms.ModelMultipleChoiceField(
            queryset=TaxRule.objects.filter(
                business=Business.objects.first(), is_active=True
            ).order_by("name"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="Reglas tributarias",
        )
        if self.instance and self.instance.pk:
            self.fields["tax_rules"].initial = self.instance.tax_rules.all()

    def clean(self):
        cleaned_data = super().clean()
        issue_date = cleaned_data.get("issue_date")
        due_date = cleaned_data.get("due_date")
        if issue_date and due_date and due_date < issue_date:
            self.add_error(
                "due_date",
                "La fecha de vencimiento no puede ser anterior a la emisión.",
            )
        return cleaned_data


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = (
            "quote_number",
            "project",
            "third_party",
            "issue_date",
            "due_date",
            "currency",
            "description",
            "notes",
        )
        labels = {
            "quote_number": "Número de cotización",
            "project": "Proyecto",
            "third_party": "Cliente/Proveedor",
            "issue_date": "Fecha de emisión",
            "due_date": "Fecha de vencimiento",
            "currency": "Moneda",
            "description": "Descripción",
            "notes": "Notas",
        }
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant_type = kwargs.pop("tenant_type", Tenant.TYPE_BUSINESS)
        super().__init__(*args, **kwargs)

        self.fields["third_party"].queryset = ThirdParty.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["third_party"].required = False
        self.fields["project"].queryset = Project.objects.all().order_by("name")

        if self.tenant_type == Tenant.TYPE_INDIVIDUAL:
            self.fields["quote_number"].required = False
            self.fields["quote_number"].help_text = (
                "Opcional. Se generará uno automático si se deja vacío."
            )
            self.fields["project"].required = False

        for field_name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})

        self.fields["tax_rules"] = forms.ModelMultipleChoiceField(
            queryset=TaxRule.objects.filter(business=Business.objects.first(), is_active=True).order_by("name"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="Reglas Tributarias",
        )
        if self.instance and self.instance.pk:
            self.fields["tax_rules"].initial = self.instance.tax_rules.all()

    def clean(self):
        cleaned_data = super().clean()
        issue_date = cleaned_data.get("issue_date")
        due_date = cleaned_data.get("due_date")
        if issue_date and due_date and due_date < issue_date:
            self.add_error(
                "due_date",
                "La fecha de vencimiento no puede ser anterior a la emisión.",
            )
        return cleaned_data


class InvoiceItemForm(forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ("description", "quantity", "unit_price")
        labels = {
            "description": "Descripción",
            "quantity": "Cantidad",
            "unit_price": "Precio unitario",
        }
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "unit_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class TaxRuleForm(forms.ModelForm):
    class Meta:
        model = TaxRule
        fields = ("name", "rule_type", "percentage", "is_active")
        labels = {
            "name": "Nombre de la regla",
            "rule_type": "Tipo de regla",
            "percentage": "Porcentaje (%)",
            "is_active": "Activa",
        }
        widgets = {
            "percentage": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update(
                    {"class": "form-control", "autocomplete": "off"}
                )

    def clean_percentage(self):
        percentage = self.cleaned_data["percentage"]
        if percentage <= 0 or percentage > 100:
            raise ValidationError("El porcentaje debe estar entre 0 y 100.")
        return percentage


class CreditNoteForm(forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = (
            "invoice",
            "third_party",
            "status",
            "issue_date",
            "currency",
            "description",
            "notes",
        )
        labels = {
            "invoice": "Factura asociada",
            "third_party": "Cliente/Proveedor",
            "status": "Estado",
            "issue_date": "Fecha de emisión",
            "currency": "Moneda",
            "description": "Descripción",
            "notes": "Notas",
        }
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant_type = kwargs.pop("tenant_type", Tenant.TYPE_BUSINESS)
        super().__init__(*args, **kwargs)
        self.fields["third_party"].queryset = ThirdParty.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["third_party"].required = False
        self.fields["invoice"].queryset = Invoice.objects.all().order_by("-issue_date")
        self.fields["invoice"].required = False

        self.fields["tax_rules"] = forms.ModelMultipleChoiceField(
            queryset=TaxRule.objects.filter(business=Business.objects.first(), is_active=True).order_by("name"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="Reglas Tributarias",
        )
        if self.instance and self.instance.pk:
            self.fields["tax_rules"].initial = self.instance.tax_rules.all()

        for field_name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})


class DebitNoteForm(forms.ModelForm):
    class Meta:
        model = DebitNote
        fields = (

            "invoice",
            "third_party",
            "status",
            "issue_date",
            "currency",
            "description",
            "notes",
        )
        labels = {
            "invoice": "Factura asociada",
            "third_party": "Cliente/Proveedor",
            "status": "Estado",
            "issue_date": "Fecha de emisión",
            "currency": "Moneda",
            "description": "Descripción",
            "notes": "Notas",
        }
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant_type = kwargs.pop("tenant_type", Tenant.TYPE_BUSINESS)
        super().__init__(*args, **kwargs)
        self.fields["third_party"].queryset = ThirdParty.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["third_party"].required = False
        self.fields["invoice"].queryset = Invoice.objects.all().order_by("-issue_date")
        self.fields["invoice"].required = False

        self.fields["tax_rules"] = forms.ModelMultipleChoiceField(
            queryset=TaxRule.objects.filter(business=Business.objects.first(), is_active=True).order_by("name"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="Reglas Tributarias",
        )
        if self.instance and self.instance.pk:
            self.fields["tax_rules"].initial = self.instance.tax_rules.all()

        for field_name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})


class CreditNoteItemForm(forms.ModelForm):
    class Meta:
        model = CreditNoteItem
        fields = ("description", "quantity", "unit_price")
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class DebitNoteItemForm(forms.ModelForm):
    class Meta:
        model = DebitNoteItem
        fields = ("description", "quantity", "unit_price")
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("payment_date", "amount", "currency", "concept", "notes")
        labels = {
            "payment_date": "Fecha de pago",
            "amount": "Monto",
            "currency": "Moneda",
            "concept": "Concepto",
            "notes": "Notas",
        }
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(
                attrs={"step": "0.01", "inputmode": "decimal"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "form-control", "autocomplete": "off"}
            )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise ValidationError("El monto debe ser mayor que cero.")
        return amount


class ApprovalRequestForm(forms.Form):
    reason = forms.CharField(
        label="Justificación",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )


ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "xlsx", "xls", "docx", "doc", "txt", "csv"}
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024


def validate_document_file(uploaded):
    extension = uploaded.name.lower().rsplit(".", 1)[-1] if "." in uploaded.name else ""
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError("Formato no permitido. Use PDF, imagen, Office, TXT o CSV.")
    if uploaded.size > MAX_DOCUMENT_SIZE:
        raise ValidationError("El archivo supera el máximo permitido de 10 MB.")
    return uploaded


class DocumentCreateForm(forms.ModelForm):
    file = forms.FileField(label="Archivo", validators=[validate_document_file])
    version_notes = forms.CharField(label="Notas de la versión", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    entity_type = forms.ChoiceField(
        label="Tipo de registro relacionado",
        required=False,
        choices=(
            ("", "Sin relación"),
            ("financial_entry", "Movimiento financiero"),
            ("third_party", "Tercero"),
            ("invoice", "Factura"),
            ("quote", "Cotización"),
            ("project", "Proyecto"),
            ("employee", "Empleado"),
        ),
    )
    entity_id = forms.ChoiceField(
        label="Registro relacionado",
        required=False,
        choices=(("", "Selecciona primero el tipo de registro"),),
    )
    RELATED_RECORD_MODELS = {
        "financial_entry": FinancialEntry,
        "third_party": ThirdParty,
        "invoice": Invoice,
        "quote": Quote,
        "project": Project,
        "employee": Employee,
    }

    class Meta:
        model = Document
        fields = ("title", "document_type", "description", "labels")
        labels = {"title": "Título", "document_type": "Tipo", "description": "Descripción", "labels": "Etiquetas"}
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["labels"].queryset = (
            DocumentTag.objects.filter(business=business) if business else DocumentTag.objects.none()
        )
        labels_field = self.fields["labels"]
        labels_field.widget = forms.CheckboxSelectMultiple(
            attrs={"class": "document-label-choice"}
        )
        labels_field.widget.choices = labels_field.choices
        selected_type = (
            self.data.get("entity_type")
            if self.is_bound
            else self.instance.entity_type
        )
        self.fields["entity_type"].widget.attrs.update({"class": "form-select", "id": "id_entity_type"})
        self.fields["entity_id"].widget.attrs.update({"class": "form-select", "id": "id_entity_id"})
        self.related_options = {}
        for entity_type, model in self.RELATED_RECORD_MODELS.items():
            queryset = model.objects.all()
            if model is not ThirdParty and business is not None:
                queryset = queryset.filter(business=business)
            records = []
            for record in queryset.order_by("-pk")[:500]:
                if entity_type == "financial_entry":
                    label = f"{record.concept} · {record.entry_date:%d/%m/%Y}"
                elif entity_type == "invoice":
                    label = record.invoice_number
                elif entity_type == "quote":
                    label = record.quote_number
                else:
                    label = str(record)
                records.append((str(record.pk), label))
            self.related_options[entity_type] = records
        self.fields["entity_id"].choices = (
            ("", "Selecciona un registro"),
            *self.related_options.get(selected_type, []),
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        entity_type = cleaned.get("entity_type")
        entity_id = cleaned.get("entity_id")
        if entity_type and not entity_id:
            self.add_error("entity_id", "Selecciona el registro relacionado.")
        if entity_id and not entity_type:
            self.add_error("entity_type", "Selecciona el tipo de registro.")
        return cleaned


class DocumentTagForm(forms.ModelForm):
    class Meta:
        model = DocumentTag
        fields = ("name",)
        labels = {"name": "Nombre de la etiqueta"}
        widgets = {"name": forms.TextInput(attrs={"class": "form-control", "maxlength": 80})}

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if DocumentTag.objects.filter(business=self.business, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Ya existe una etiqueta con ese nombre.")
        return name


class DocumentVersionForm(forms.Form):
    file = forms.FileField(label="Nueva versión", validators=[validate_document_file], widget=forms.ClearableFileInput(attrs={"class": "form-control"}))
    notes = forms.CharField(label="Cambios realizados", required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}))


class ApprovalDecisionForm(forms.Form):
    action = forms.ChoiceField(
        choices=((ApprovalRequest.APPROVED, "Aprobar"), (ApprovalRequest.REJECTED, "Rechazar")),
        widget=forms.HiddenInput(),
    )
    decision_notes = forms.CharField(
        label="Observaciones de la decisión",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == ApprovalRequest.REJECTED and not cleaned.get("decision_notes", "").strip():
            self.add_error("decision_notes", "Explique el motivo del rechazo.")
        return cleaned


class BankStatementImportCSVForm(forms.Form):
    statement_name = forms.CharField(
        label="Nombre / referencia (opcional)", required=False
    )
    bank_account = forms.ModelChoiceField(
        label="Cuenta bancaria",
        queryset=None,
        required=True,
    )
    file = forms.FileField(label="Archivo CSV o Excel")
    delimiter = forms.ChoiceField(
        label="Separador",
        choices=((",", "Coma (, )"), (";", "Punto y coma (;)")),
        initial=",",
        required=True,
    )
    has_header = forms.BooleanField(
        label="El CSV tiene encabezado", required=False, initial=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tenantdata.models import BankAccount

        self.fields["bank_account"].queryset = BankAccount.objects.all().order_by(
            "name"
        )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = uploaded.name.lower().rsplit(".", 1)[-1]
        if extension not in {"csv", "xlsx"}:
            raise ValidationError("Use un archivo CSV o Excel (.xlsx).")
        return uploaded


class ReconciliationManualForm(forms.Form):
    payment = forms.ModelChoiceField(
        queryset=Payment.objects.none(), required=False, label="Pago existente"
    )
    financial_entry = forms.ModelChoiceField(
        queryset=FinancialEntry.objects.none(),
        required=False,
        label="Movimiento financiero",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment"].queryset = Payment.objects.select_related(
            "financial_entry"
        ).order_by("-payment_date")
        self.fields["financial_entry"].queryset = FinancialEntry.objects.filter(
            status__in=[FinancialEntry.PENDING, FinancialEntry.PARTIAL]
        ).order_by("-entry_date")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("payment") and not cleaned.get("financial_entry"):
            raise ValidationError("Seleccione un pago o un movimiento financiero.")
        return cleaned


class ReconciliationConfirmForm(forms.Form):
    reconciliation_id = forms.IntegerField(widget=forms.HiddenInput())
    action = forms.ChoiceField(
        label="Acción",
        choices=(("confirm", "Confirmar"), ("reject", "Rechazar")),
        widget=forms.RadioSelect,
    )
    notes = forms.CharField(
        label="Notas (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ("name", "bank_name", "base_currency", "is_active")
        labels = {
            "name": "Nombre",
            "bank_name": "Banco",
            "base_currency": "Moneda base",
            "is_active": "Activa",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update(
                    {"class": "form-control", "autocomplete": "off"}
                )
