from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from tenantdata.models import (
    AuditEvent,
    Business,
    CurrencyRate,
    Employee,
    FinancialEntry,
    ThirdParty,
)

from businessmanagement.models import Domain, Tenant
from businessmanagement.views import ensure_default_tenant_groups
from businessmanagement.modules import AVAILABLE_MODULES, MODULES_INDIVIDUAL, MODULES_BUSINESS


class Command(BaseCommand):
    help = "Create a demo tenant with sample company, admin user, groups, third parties, currency rates and financial entries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema", default="demo", help="Schema name for the tenant"
        )
        parser.add_argument(
            "--domain",
            default="demo.127.0.0.1.nip.io",
            help="Primary domain for the tenant",
        )
        parser.add_argument(
            "--name", default="Demo Company", help="Tenant display name"
        )
        parser.add_argument(
            "--business-name",
            default="Demo Business S.A.",
            help="Business name inside tenant",
        )
        parser.add_argument(
            "--type",
            default=Tenant.TYPE_BUSINESS,
            choices=[Tenant.TYPE_BUSINESS, Tenant.TYPE_INDIVIDUAL],
            help="Tenant type (business or individual)",
        )

    def handle(self, *args, **options):
        schema_name = options["schema"]
        domain_name = options["domain"]
        tenant_name = options["name"]
        business_name = options["business_name"]
        tenant_type = options["type"]

        # Get all module names from AVAILABLE_MODULES
        all_modules = [m[0] for m in AVAILABLE_MODULES]
        
        # Use the predefined module lists
        if tenant_type == Tenant.TYPE_INDIVIDUAL:
            enabled_modules = MODULES_INDIVIDUAL + all_modules
        else:
            enabled_modules = MODULES_BUSINESS + all_modules
        
        # Remove duplicates while preserving order
        seen = set()
        enabled_modules = [x for x in enabled_modules if not (x in seen or seen.add(x))]

        tenant, created = Tenant.objects.get_or_create(
            schema_name=schema_name,
            defaults={
                "name": tenant_name,
                "tenant_type": tenant_type,
                "enabled_modules": enabled_modules,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Tenant creado: {schema_name}"))
        else:
            # Update existing tenant with all modules
            tenant.enabled_modules = enabled_modules
            tenant.tenant_type = tenant_type
            tenant.save(update_fields=['enabled_modules', 'tenant_type'])
            self.stdout.write(self.style.WARNING(f"Tenant existente actualizado: {schema_name}"))

        domain, domain_created = Domain.objects.get_or_create(
            domain=domain_name,
            defaults={"tenant": tenant, "is_primary": True},
        )
        if not domain_created:
            domain.tenant = tenant
            domain.is_primary = True
            domain.save()
        self.stdout.write(self.style.SUCCESS(f"Domain asegurado: {domain_name}"))

        with schema_context(tenant.schema_name):
            business, _ = Business.objects.get_or_create(
                business_name=business_name,
                defaults={
                    "name_business_owner": "Demo",
                    "last_name_business_owner": "Admin",
                    "business_phone": "+57 300 000 0000",
                    "business_email": "demo@example.com",
                    "business_address": "Calle Demo 123",
                    "description": "Empresa demo generada por comando de prueba.",
                },
            )
            user_model = get_user_model()
            user, user_created = user_model.objects.get_or_create(
                username="demo_admin",
                defaults={
                    "email": "demo_admin@example.com",
                    "first_name": "Demo",
                    "last_name": "Administrador",
                    "is_staff": True,
                    "is_superuser": True,
                },
            )
            if user_created:
                user.set_password("demo1234")
                user.save()

            # Asegurar grupos predeterminados
            ensure_default_tenant_groups()

            # Asignar al usuario administrador al grupo de Administrador de empresa
            admin_group = Group.objects.get(name="Administrador de empresa")
            user.groups.add(admin_group)

            # Asegurar perfil de empleado para el admin
            Employee.objects.get_or_create(
                user=user,
                defaults={
                    "first_name": user.first_name or "Demo",
                    "last_name": user.last_name or "Admin",
                    "email": user.email,
                    "phone": "+57 300 000 0000",
                    "position": "Administrador Global",
                    "business": business,
                },
            )

            self._create_sample_third_parties()
            self._create_sample_currency_rates()
            self._create_sample_financial_entries(business, user)
            AuditEvent.objects.create(
                actor=user,
                action=AuditEvent.CREATE,
                entity="tenant_demo_seed",
                entity_id=tenant.schema_name,
                summary="Demo tenant y datos iniciales creados.",
                metadata={
                    "business": business.business_name,
                    "admin_username": user.username,
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo tenant inicializado correctamente."))
        self.stdout.write(
            self.style.SUCCESS("Usuario: demo_admin / Contraseña: demo1234")
        )

    def _create_sample_third_parties(self):
        third_parties = [
            {
                "name": "Super Clientes S.A.",
                "third_party_type": ThirdParty.CUSTOMER,
                "email": "cliente@example.com",
                "phone": "+57 300 111 1111",
            },
            {
                "name": "Proveedores Demo S.A.",
                "third_party_type": ThirdParty.SUPPLIER,
                "email": "proveedor@example.com",
                "phone": "+57 300 222 2222",
            },
            {
                "name": "Cliente y Proveedor S.A.",
                "third_party_type": ThirdParty.BOTH,
                "email": "crm@example.com",
                "phone": "+57 300 333 3333",
            },
        ]
        for data in third_parties:
            ThirdParty.objects.update_or_create(
                name=data["name"],
                defaults={
                    "identification": "999999999",
                    "email": data["email"],
                    "phone": data["phone"],
                    "address": "Calle 1 # 2-3",
                    "third_party_type": data["third_party_type"],
                    "is_active": True,
                },
            )

    def _create_sample_currency_rates(self):
        CurrencyRate.objects.update_or_create(
            currency=CurrencyRate.USD,
            rate_date="2026-01-01",
            defaults={"rate_to_local": "4100.00", "source": "demo_seed"},
        )
        CurrencyRate.objects.update_or_create(
            currency=CurrencyRate.EUR,
            rate_date="2026-01-01",
            defaults={"rate_to_local": "4500.00", "source": "demo_seed"},
        )
        CurrencyRate.objects.update_or_create(
            currency=CurrencyRate.BINANCE,
            rate_date="2026-01-01",
            defaults={"rate_to_local": "1.00", "source": "demo_seed"},
        )

    def _create_sample_financial_entries(self, business, user):
        third_party = ThirdParty.objects.filter(is_active=True).first()
        entries = [
            {
                "concept": "Venta de producto demo",
                "entry_type": FinancialEntry.INCOME,
                "status": FinancialEntry.PAID,
                "amount": "1250000.00",
                "currency": "COP",
                "entry_date": "2026-06-01",
                "due_date": "2026-06-10",
            },
            {
                "concept": "Pago de proveedor",
                "entry_type": FinancialEntry.EXPENSE,
                "status": FinancialEntry.PAID,
                "amount": "600000.00",
                "currency": "COP",
                "entry_date": "2026-06-02",
                "due_date": "2026-06-12",
            },
            {
                "concept": "Cuenta por cobrar demo",
                "entry_type": FinancialEntry.ACCOUNT_RECEIVABLE,
                "status": FinancialEntry.PENDING,
                "amount": "350000.00",
                "currency": "COP",
                "entry_date": "2026-06-03",
                "due_date": "2026-06-20",
            },
        ]
        for entry_data in entries:
            FinancialEntry.objects.update_or_create(
                concept=entry_data["concept"],
                defaults={
                    "business": business,
                    "third_party": third_party,
                    "created_by": user,
                    "entry_type": entry_data["entry_type"],
                    "status": entry_data["status"],
                    "amount": entry_data["amount"],
                    "currency": entry_data["currency"],
                    "entry_date": entry_data["entry_date"],
                    "due_date": entry_data["due_date"],
                    "notes": "Entrada inicial de demo.",
                },
            )
