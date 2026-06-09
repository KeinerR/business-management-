import os
import requests
from celery import shared_task
from django.conf import settings
from django.db import connection
from django_tenants.utils import schema_context
from .models import Tenant
from tenantdata.models import CurrencyRate, AuditEvent
from datetime import date


@shared_task(bind=True, default_retry_delay=60, max_retries=3)
def update_currency_rates(self):
    """Iterate tenants and update CurrencyRate from external API configured in CURRENCY_API_URL.

    Expected JSON format (example):
    {
        "rates": [
            {"currency": "USD", "rate_to_local": 5000.12, "date": "2026-06-04", "source": "example"},
            ...
        ]
    }
    """
    api_url = os.getenv('CURRENCY_API_URL')
    if not api_url:
        # No API configured; nothing to do
        return 'no_api_configured'

    tenants = Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
    for tenant in tenants:
        try:
            with schema_context(tenant.schema_name):
                resp = requests.get(api_url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get('rates', []):
                    currency = item.get('currency')
                    rate_value = item.get('rate_to_local')
                    rate_date = item.get('date') or date.today().isoformat()
                    source = item.get('source', 'external')
                    if currency and rate_value is not None:
                        CurrencyRate.objects.update_or_create(
                            currency=currency,
                            rate_date=rate_date,
                            defaults={'rate_to_local': rate_value, 'source': source},
                        )
                AuditEvent.objects.create(actor=None, action=AuditEvent.UPDATE, entity='currency_rate', entity_id='', summary='Tasas actualizadas por tarea periódica', metadata={'tenant': tenant.schema_name})
        except Exception as exc:
            # If a tenant update fails, log and continue
            try:
                with schema_context(settings.PUBLIC_SCHEMA_NAME):
                    AuditEvent.objects.create(actor=None, action=AuditEvent.ACCESS, entity='currency_rate_update', entity_id=tenant.schema_name, summary=f'Error actualizando tasas: {str(exc)}', metadata={})
            except Exception:
                pass
            continue

    return 'ok'
