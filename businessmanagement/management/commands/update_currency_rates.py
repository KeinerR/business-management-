from django.core.management.base import BaseCommand, CommandError

from businessmanagement.tasks import update_currency_rates


class Command(BaseCommand):
    help = "Fetch USD/EUR reference rates once and update active tenants without overwriting manual rates."

    def handle(self, *args, **options):
        try:
            result = update_currency_rates()
        except Exception as exc:
            raise CommandError("No se pudieron actualizar todas las tasas. Revise la conectividad con open.er-api.com y los logs.") from exc
        self.stdout.write(self.style.SUCCESS(f"Tasas actualizadas: {result['updated_tenants']} tenants."))
