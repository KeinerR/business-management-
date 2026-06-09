from django.conf import settings
from django.core.management.base import BaseCommand

from businessmanagement.models import Domain, Tenant


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

        demo_tenant, _ = Tenant.objects.get_or_create(
            schema_name="demo",
            defaults={"name": "Demo"},
        )
        self._ensure_domain("demo.127.0.0.1.nip.io", demo_tenant, is_primary=True)

        self.stdout.write(self.style.SUCCESS("Development tenants are ready."))

    def _ensure_domain(self, domain, tenant, is_primary=False):
        Domain.objects.update_or_create(
            domain=domain,
            defaults={"tenant": tenant, "is_primary": is_primary},
        )
