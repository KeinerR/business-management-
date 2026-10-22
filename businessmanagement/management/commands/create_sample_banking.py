"""
Create sample bank accounts for demo tenant.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from tenantdata.models import BankAccount
from businessmanagement.models import Tenant

class Command(BaseCommand):
    help = 'Create sample bank accounts for demo tenant'

    def add_arguments(self, parser):
        parser.add_argument('--schema', default='demo', help='Tenant schema name')

    def handle(self, *args, **options):
        schema_name = options['schema']
        tenant = Tenant.objects.filter(schema_name=schema_name).first()
        
        if not tenant:
            self.stdout.write(self.style.ERROR(f'Tenant {schema_name} not found'))
            return
        
        with schema_context(tenant.schema_name):
            from tenantdata.models import Business
            business = Business.objects.first()
            
            if not business:
                self.stdout.write(self.style.ERROR('No business found. Create a business first.'))
                return
            
            banks = [
                {
                    "name": "Cuenta Corriente Principal",
                    "bank_name": "Banco de Bogotá",
                    "base_currency": "COP",
                },
                {
                    "name": "Cuenta de Ahorros",
                    "bank_name": "Banco de Bogotá",
                    "base_currency": "COP",
                },
                {
                    "name": "Cuenta美元 (USD)",
                    "bank_name": "Banco de Bogotá",
                    "base_currency": "USD",
                },
            ]
            
            for bank_data in banks:
                bank, created = BankAccount.objects.get_or_create(
                    name=bank_data["name"],
                    bank_name=bank_data["bank_name"],
                    defaults={
                        "business": business,
                        "base_currency": bank_data["base_currency"],
                        "is_active": True,
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created: {bank.name}'))
                else:
                    self.stdout.write(f'Already exists: {bank.name}')
            
            self.stdout.write(self.style.SUCCESS('Done!'))
