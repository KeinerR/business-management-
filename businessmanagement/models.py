from django.conf import settings
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    TYPE_BUSINESS = "business"
    TYPE_INDIVIDUAL = "individual"
    TYPE_CHOICES = (
        (TYPE_BUSINESS, "Empresa / Jurídica"),
        (TYPE_INDIVIDUAL, "Persona Natural"),
    )

    name = models.CharField(max_length=100)
    tenant_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_BUSINESS
    )
    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)
    auto_create_schema = True  # crea el schema en DB automáticamente
    # Módulos habilitados para el tenant (almacenados como lista JSON)
    # Ejemplo: ["finances", "projects", "invoices", "employees", "third_parties"]
    enabled_modules = models.JSONField(default=list, blank=True)

    def is_module_enabled(self, module_name):
        # Si la lista de módulos está vacía, no tiene nada habilitado
        # (Cambiado de habilitar todo por defecto a ser restrictivo)
        if not self.enabled_modules:
            return False
        return module_name in self.enabled_modules


class Domain(DomainMixin):
    pass


class PlatformBusiness(Tenant):
    class Meta:
        proxy = True
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"


class PlatformEmployee(Tenant):
    class Meta:
        proxy = True
        verbose_name = "Empleados por empresa"
        verbose_name_plural = "Empleados por empresa"


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
        related_name="legacy_employee_profile",
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
