from django.conf import settings
from django.core.management.base import BaseCommand

from businessmanagement.models import Domain, Tenant
from businessmanagement.modules import AVAILABLE_MODULES, MODULES_INDIVIDUAL, MODULES_BUSINESS


class Command(BaseCommand):
    help = "Create development tenants and domains used by Docker Compose."

    def handle(self, *args, **options):
        public_tenant, _ = Tenant.objects.get_or_create(
            schema_name=settings.PUBLIC_SCHEMA_NAME,
            defaults={"name": "Public"},
        )

        self._ensure_domain("localhost", public_tenant, is_primary=True)
        self._ensure_domain("127.0.0.1", public_tenant)
        self._ensure_domain("127.0.0.1.nip.io", public_tenant)

        # Get all module names
        all_modules = [m[0] for m in AVAILABLE_MODULES]
        all_modules_set = set(MODULES_BUSINESS + all_modules)
        
        demo_tenant, created = Tenant.objects.get_or_create(
            schema_name="demo",
            defaults={"name": "Demo", "tenant_type": Tenant.TYPE_BUSINESS},
        )
        if not created:
            # Update existing tenant with all modules
            existing = set(demo_tenant.enabled_modules or [])
            demo_tenant.enabled_modules = sorted(list(existing | all_modules_set))
            demo_tenant.save(update_fields=['enabled_modules'])
            self.stdout.write(self.style.WARNING(f"Updated demo tenant with {len(demo_tenant.enabled_modules)} modules"))
        else:
            demo_tenant.enabled_modules = sorted(list(all_modules_set))
            demo_tenant.save(update_fields=['enabled_modules'])
            self.stdout.write(self.style.SUCCESS(f"Created demo tenant with {len(all_modules_set)} modules"))

        self._ensure_domain("demo.127.0.0.1.nip.io", demo_tenant, is_primary=True)

        self.stdout.write(self.style.SUCCESS("Development tenants are ready with all modules."))

    def _ensure_domain(self, domain, tenant, is_primary=False):
        Domain.objects.update_or_create(
            domain=domain,
            defaults={"tenant": tenant, "is_primary": is_primary},
        )
