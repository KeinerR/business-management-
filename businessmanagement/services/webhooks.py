import logging

from celery.exceptions import OperationalError
from django.db import connection, transaction
from django_tenants.utils import schema_context

from tenantdata.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)


def dispatch_webhook_event(event, payload):
    schema_name = connection.schema_name
    endpoints = WebhookEndpoint.objects.filter(
        is_active=True,
        event_types__contains=[event],
    )
    for endpoint in endpoints:
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event=event,
            target_url=endpoint.url,
            payload=payload,
        )
        transaction.on_commit(
            lambda delivery_id=delivery.pk: _enqueue_delivery(delivery_id, schema_name)
        )


def _enqueue_delivery(delivery_id, schema_name):
    from businessmanagement.tasks import deliver_webhook

    try:
        deliver_webhook.delay(delivery_id, schema_name)
    except OperationalError as exc:
        with schema_context(schema_name):
            WebhookDelivery.objects.filter(
                pk=delivery_id, status=WebhookDelivery.PENDING
            ).update(
                status=WebhookDelivery.FAILED,
                last_error=f"No se pudo programar la entrega: {exc}"[:2000],
            )
        logger.exception("No se pudo programar la entrega webhook %s", delivery_id)
