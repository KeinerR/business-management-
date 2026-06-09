from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils.html import format_html
from django_tenants.utils import schema_context

from tenantdata.models import AuditEvent, Business, Employee

from .models import Domain, PlatformBusiness, PlatformEmployee, Tenant


def is_public_schema():
    return connection.schema_name == settings.PUBLIC_SCHEMA_NAME


class PublicSchemaOnlyAdminMixin:
    def has_module_permission(self, request):
        return is_public_schema() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return is_public_schema() and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return is_public_schema() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_public_schema() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_public_schema() and super().has_delete_permission(request, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_public_schema():
            return queryset.none()
        return queryset


class TenantCreationAdminForm(forms.ModelForm):
    domain = forms.CharField(
        label="Dominio",
        help_text="Ejemplo: empresa.127.0.0.1.nip.io, sin http ni puerto",
    )
    is_active = forms.BooleanField(label="Activo", required=False)
    enabled_modules = forms.MultipleChoiceField(
        choices=(
            ("finances", "Finanzas (Movimientos)"),
            ("projects", "Proyectos"),
            ("invoices", "Facturas"),
            ("employees", "Empleados"),
            ("third_parties", "Terceros (CRM)"),
            ("categories", "Categorías Financieras"),
        ),
        widget=forms.CheckboxSelectMultiple,
        label="Módulos Habilitados",
        required=False,
    )
    name_business_owner = forms.CharField(label="Nombre del propietario")
    last_name_business_owner = forms.CharField(label="Apellido del propietario")
    business_name = forms.CharField(label="Nombre de la empresa")
    business_phone = forms.CharField(label="Telefono")
    business_email = forms.EmailField(label="Email de la empresa")
    business_address = forms.CharField(label="Direccion")
    description = forms.CharField(
        label="Descripcion", required=False, widget=forms.Textarea
    )
    admin_username = forms.CharField(label="Usuario administrador", required=False)
    admin_password = forms.CharField(
        label="Contrasena", required=False, widget=forms.PasswordInput
    )
    admin_first_name = forms.CharField(label="Nombre del usuario", required=False)
    admin_last_name = forms.CharField(label="Apellido del usuario", required=False)
    admin_email = forms.EmailField(label="Email del usuario", required=False)
    admin_phone = forms.CharField(label="Telefono del usuario", required=False)

    class Meta:
        model = Tenant
        fields = ("name", "schema_name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            primary_domain = self.instance.domains.filter(is_primary=True).first()
            if primary_domain:
                self.initial["domain"] = primary_domain.domain
            if self.instance.schema_name != settings.PUBLIC_SCHEMA_NAME:
                employee = None
                try:
                    with schema_context(self.instance.schema_name):
                        business = Business.objects.first()
                        if business:
                            self.initial.update(
                                {
                                    "name_business_owner": business.name_business_owner,
                                    "last_name_business_owner": business.last_name_business_owner,
                                    "business_name": business.business_name,
                                    "business_phone": business.business_phone,
                                    "business_email": business.business_email,
                                    "business_address": business.business_address,
                                    "description": business.description,
                                }
                            )
                        employee = (
                            Employee.objects.select_related("user")
                            .filter(position="Administrador")
                            .first()
                        )
                        if employee is None:
                            employee = Employee.objects.select_related("user").first()
                except DatabaseError:
                    transaction.set_rollback(True)
                    connection.set_schema_to_public()

                if employee:
                    self.initial.update(
                        {
                            "admin_username": employee.user.username,
                            "admin_first_name": employee.first_name,
                            "admin_last_name": employee.last_name,
                            "admin_email": employee.email,
                            "admin_phone": employee.phone,
                        }
                    )
            self.fields["admin_username"].required = True
            self.fields["admin_password"].required = True
            self.fields["admin_first_name"].required = True
            self.fields["admin_last_name"].required = True
            self.fields["admin_email"].required = True
            self.fields["admin_phone"].required = True

    def clean_domain(self):
        domain = self.cleaned_data["domain"].strip().lower()
        domain = domain.removeprefix("http://").removeprefix("https://").split("/")[0]
        domain = domain.split(":")[0]
        queryset = Domain.objects.filter(domain=domain)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(tenant=self.instance)
        if queryset.exists():
            raise forms.ValidationError("Ya existe un tenant con este dominio.")
        return domain

    def clean_schema_name(self):
        schema_name = self.cleaned_data["schema_name"].strip().lower()
        if schema_name == settings.PUBLIC_SCHEMA_NAME:
            raise forms.ValidationError(
                "Este schema esta reservado para la plataforma."
            )
        return schema_name


@admin.register(Tenant)
class TenantAdmin(PublicSchemaOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "schema_name",
        "is_active",
        "primary_domain",
        "tenant_business_name",
        "tenant_admin_user",
        "created_on",
    )
    search_fields = ("name", "schema_name")
    list_filter = ("is_active",)
    add_form = TenantCreationAdminForm

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = self.add_form
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if obj is not None:
            if obj.schema_name != settings.PUBLIC_SCHEMA_NAME:
                return (
                    (
                        "Tenant",
                        {
                            "fields": (
                                "name",
                                "schema_name",
                                "is_active",
                                "domain",
                                "enabled_modules",
                            ),
                        },
                    ),
                    (
                        "Empresa",
                        {
                            "fields": (
                                "name_business_owner",
                                "last_name_business_owner",
                                "business_name",
                                "business_phone",
                                "business_email",
                                "business_address",
                                "description",
                            ),
                        },
                    ),
                    (
                        "Usuario administrador",
                        {
                            "fields": (
                                "admin_username",
                                "admin_password",
                                "admin_first_name",
                                "admin_last_name",
                                "admin_email",
                                "admin_phone",
                            ),
                        },
                    ),
                )
            return (
                (
                    "Tenant",
                    {
                        "fields": ("name", "schema_name", "is_active", "domain"),
                    },
                ),
            )
        return (
            (
                "Tenant",
                {
                    "fields": ("name", "schema_name", "domain", "enabled_modules"),
                },
            ),
            (
                "Empresa",
                {
                    "fields": (
                        "name_business_owner",
                        "last_name_business_owner",
                        "business_name",
                        "business_phone",
                        "business_email",
                        "business_address",
                        "description",
                    ),
                },
            ),
            (
                "Usuario inicial de la empresa",
                {
                    "fields": (
                        "admin_username",
                        "admin_password",
                        "admin_first_name",
                        "admin_last_name",
                        "admin_email",
                        "admin_phone",
                    ),
                },
            ),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change:
            domain_value = form.cleaned_data["domain"]
            primary_domain = Domain.objects.filter(tenant=obj, is_primary=True).first()
            if primary_domain:
                primary_domain.domain = domain_value
                primary_domain.save()
            else:
                Domain.objects.create(
                    domain=domain_value,
                    tenant=obj,
                    is_primary=True,
                )

            with schema_context(obj.schema_name):
                business = Business.objects.first()
                if not business:
                    business = Business()
                business.name_business_owner = form.cleaned_data["name_business_owner"]
                business.last_name_business_owner = form.cleaned_data[
                    "last_name_business_owner"
                ]
                business.business_name = form.cleaned_data["business_name"]
                business.business_phone = form.cleaned_data["business_phone"]
                business.business_email = form.cleaned_data["business_email"]
                business.business_address = form.cleaned_data["business_address"]
                business.description = form.cleaned_data["description"]
                business.save()

                admin_username = form.cleaned_data.get("admin_username")
                admin_password = form.cleaned_data.get("admin_password")
                admin_first_name = form.cleaned_data.get("admin_first_name")
                admin_last_name = form.cleaned_data.get("admin_last_name")
                admin_email = form.cleaned_data.get("admin_email")
                admin_phone = form.cleaned_data.get("admin_phone")
                if admin_username:
                    employee = (
                        Employee.objects.select_related("user")
                        .filter(position="Administrador")
                        .first()
                    )
                    if employee is None:
                        employee = Employee.objects.select_related("user").first()
                    if employee:
                        user = employee.user
                        user.username = admin_username
                        if admin_password:
                            user.set_password(admin_password)
                        user.email = admin_email or user.email
                        user.first_name = admin_first_name or user.first_name
                        user.last_name = admin_last_name or user.last_name
                        user.is_staff = True
                        user.is_superuser = True
                        user.save()
                        employee.first_name = admin_first_name or employee.first_name
                        employee.last_name = admin_last_name or employee.last_name
                        employee.email = admin_email or employee.email
                        employee.phone = admin_phone or employee.phone
                        employee.save()
                    else:
                        # No existe empleado: crear user y employee nuevos en el esquema del tenant
                        user = get_user_model().objects.create_user(
                            username=admin_username,
                            password=admin_password or None,
                            email=admin_email or "",
                            first_name=admin_first_name or "",
                            last_name=admin_last_name or "",
                            is_staff=True,
                            is_superuser=True,
                        )
                        Employee.objects.create(
                            user=user,
                            first_name=admin_first_name or "",
                            last_name=admin_last_name or "",
                            email=admin_email or "",
                            phone=admin_phone or "",
                            position="Administrador",
                            business=business,
                        )
            return

        Domain.objects.create(
            domain=form.cleaned_data["domain"],
            tenant=obj,
            is_primary=True,
        )

        with schema_context(obj.schema_name):
            for group_name in (
                "Administrador de empresa",
                "Operador financiero",
                "Solo lectura",
            ):
                Group.objects.get_or_create(name=group_name)
            business = Business.objects.create(
                name_business_owner=form.cleaned_data["name_business_owner"],
                last_name_business_owner=form.cleaned_data["last_name_business_owner"],
                business_name=form.cleaned_data["business_name"],
                business_phone=form.cleaned_data["business_phone"],
                business_email=form.cleaned_data["business_email"],
                business_address=form.cleaned_data["business_address"],
                description=form.cleaned_data["description"],
            )
            user = get_user_model().objects.create_user(
                username=form.cleaned_data["admin_username"],
                password=form.cleaned_data["admin_password"],
                email=form.cleaned_data["admin_email"],
                first_name=form.cleaned_data["admin_first_name"],
                last_name=form.cleaned_data["admin_last_name"],
                is_staff=True,
                is_superuser=True,
            )
            Employee.objects.create(
                user=user,
                first_name=form.cleaned_data["admin_first_name"],
                last_name=form.cleaned_data["admin_last_name"],
                email=form.cleaned_data["admin_email"],
                phone=form.cleaned_data["admin_phone"],
                position="Administrador",
                business=business,
            )
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.CREATE,
                entity="tenant_bootstrap",
                entity_id=obj.schema_name,
                summary="Tenant creado con empresa, admin inicial y roles base.",
                metadata={
                    "business": business.business_name,
                    "admin_username": user.username,
                },
            )

        connection.set_schema_to_public()
        messages.success(
            request, "Tenant, dominio, empresa y usuario inicial creados correctamente."
        )

    @admin.display(description="Dominio")
    def primary_domain(self, obj):
        domain = obj.domains.filter(is_primary=True).first() or obj.domains.first()
        if domain is None:
            return "-"
        return domain.domain

    @admin.display(description="Empresa")
    def tenant_business_name(self, obj):
        business = self._get_tenant_business(obj)
        if business is None:
            return "-"
        return business.business_name

    @admin.display(description="Usuario inicial")
    def tenant_admin_user(self, obj):
        if obj.schema_name == settings.PUBLIC_SCHEMA_NAME:
            return "-"
        try:
            with schema_context(obj.schema_name):
                employee = (
                    Employee.objects.select_related("user")
                    .filter(position="Administrador")
                    .first()
                )
                if employee is None:
                    employee = Employee.objects.select_related("user").first()
                return employee.user.username if employee else "-"
        except DatabaseError:
            connection.set_schema_to_public()
            return "Sin migrar"

    def _get_tenant_business(self, tenant):
        if tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            return None
        try:
            with schema_context(tenant.schema_name):
                return Business.objects.first()
        except DatabaseError:
            connection.set_schema_to_public()
            return None


@admin.register(Domain)
class DomainAdmin(PublicSchemaOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    search_fields = ("domain", "tenant__name")


class PlatformDirectoryAdmin(PublicSchemaOnlyAdminMixin, admin.ModelAdmin):
    actions = None

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Dominio")
    def primary_domain(self, obj):
        domain = obj.domains.filter(is_primary=True).first() or obj.domains.first()
        if domain is None:
            return "-"
        return domain.domain

    @admin.display(description="Tenant")
    def tenant_link(self, obj):
        url = reverse("admin:businessmanagement_tenant_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.schema_name)


@admin.register(PlatformBusiness)
class PlatformBusinessAdmin(PlatformDirectoryAdmin):
    list_display = (
        "business_name",
        "business_email",
        "business_phone",
        "primary_domain",
        "tenant_link",
    )
    search_fields = ("name", "schema_name", "domains__domain")

    def has_change_permission(self, request, obj=None):
        return (
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Empresa")
    def business_name(self, obj):
        business = self._get_business(obj)
        return business.business_name if business else "-"

    @admin.display(description="Email")
    def business_email(self, obj):
        business = self._get_business(obj)
        return business.business_email if business else "-"

    @admin.display(description="Telefono")
    def business_phone(self, obj):
        business = self._get_business(obj)
        return business.business_phone if business else "-"

    def _get_business(self, tenant):
        try:
            with schema_context(tenant.schema_name):
                return Business.objects.first()
        except DatabaseError:
            connection.set_schema_to_public()
            return None


@admin.register(PlatformEmployee)
class PlatformEmployeeAdmin(PlatformDirectoryAdmin):
    list_display = (
        "tenant_name",
        "employee_count",
        "admin_user",
        "primary_domain",
        "tenant_link",
    )
    search_fields = ("name", "schema_name", "domains__domain")

    @admin.display(description="Empresa")
    def tenant_name(self, obj):
        return obj.name

    @admin.display(description="Empleados")
    def employee_count(self, obj):
        try:
            with schema_context(obj.schema_name):
                return Employee.objects.count()
        except DatabaseError:
            connection.set_schema_to_public()
            return "Sin migrar"

    @admin.display(description="Usuario admin")
    def admin_user(self, obj):
        try:
            with schema_context(obj.schema_name):
                employee = (
                    Employee.objects.select_related("user")
                    .filter(position="Administrador")
                    .first()
                )
                if employee is None:
                    employee = Employee.objects.select_related("user").first()
                return employee.user.username if employee else "-"
        except DatabaseError:
            connection.set_schema_to_public()
            return "Sin migrar"
