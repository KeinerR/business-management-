"""
Command to update tenant enabled_modules with all available modules.
"""
from django.core.management.base import BaseCommand
from businessmanagement.models import Tenant
from businessmanagement.modules import AVAILABLE_MODULES, MODULES_BUSINESS

class Command(BaseCommand):
    help = 'Update tenant enabled_modules with all available modules'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=int,
            help='Specific tenant ID to update (default: all)',
        )

    def handle(self, *args, **options):
        tenant_id = options.get('tenant_id')
        
        # Get all module names
        all_modules = [m[0] for m in AVAILABLE_MODULES]
        
        if tenant_id:
            tenants = Tenant.objects.filter(pk=tenant_id)
        else:
            tenants = Tenant.objects.all()
        
        for tenant in tenants:
            old_modules = tenant.enabled_modules or []
            # Combine existing with all new modules
            updated_modules = list(set(old_modules + all_modules))
            tenant.enabled_modules = sorted(updated_modules)
            tenant.save(update_fields=['enabled_modules'])
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated tenant {tenant.name}: {len(updated_modules)} modules enabled'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f'Updated {tenants.count()} tenants with all modules')
        )
