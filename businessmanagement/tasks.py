import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import urlsplit

import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context
from tenantdata.models import Invoice, Quote, AuditEvent, WebhookDelivery
from businessmanagement.models import Tenant
from businessmanagement.services.notifications import notify_users

logger = logging.getLogger(__name__)


def _ensure_public_webhook_destination(url):
    hostname = urlsplit(url).hostname
    if not hostname:
        raise ValueError("La URL del webhook no contiene un host válido.")

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(
                    hostname, urlsplit(url).port or 443, type=socket.SOCK_STREAM
                )
            }
        except socket.gaierror as exc:
            raise ValueError("No se pudo resolver el host del webhook.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("El webhook no puede dirigirse a redes privadas o reservadas.")


@shared_task(bind=True, max_retries=5)
def deliver_webhook(self, delivery_id, schema_name):
    with schema_context(schema_name):
        with transaction.atomic():
            delivery = (
                WebhookDelivery.objects.select_for_update()
                .select_related("endpoint")
                .get(pk=delivery_id)
            )
            if delivery.status != WebhookDelivery.PENDING:
                return delivery.status
            delivery.attempts += 1
            delivery.last_attempt_at = timezone.now()
            delivery.save(update_fields=("attempts", "last_attempt_at"))
            url = delivery.target_url
            secret = delivery.endpoint.secret
            payload = delivery.payload
            event = delivery.event

    try:
        _ensure_public_webhook_destination(url)
    except ValueError as exc:
        with schema_context(schema_name):
            WebhookDelivery.objects.filter(pk=delivery_id).update(
                status=WebhookDelivery.FAILED,
                last_error=str(exc)[:2000],
            )
        return WebhookDelivery.FAILED

    body = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-SystemManager-Event": event,
        "X-SystemManager-Signature": f"sha256={signature}",
        "X-SystemManager-Delivery": str(delivery_id),
    }

    try:
        response = requests.post(
            url,
            data=body,
            headers=headers,
            timeout=(3, 10),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return _retry_webhook(self, delivery_id, schema_name, exc)

    update_fields = {
        "response_status": response.status_code,
        "response_body": response.text[:2000],
    }
    if 200 <= response.status_code < 300:
        update_fields.update(
            status=WebhookDelivery.DELIVERED,
            delivered_at=timezone.now(),
            last_error="",
        )
        with schema_context(schema_name):
            WebhookDelivery.objects.filter(pk=delivery_id).update(**update_fields)
        return WebhookDelivery.DELIVERED

    error = f"El destino respondió HTTP {response.status_code}."
    if response.status_code == 429 or response.status_code >= 500:
        return _retry_webhook(
            self, delivery_id, schema_name, RuntimeError(error), update_fields
        )

    update_fields.update(status=WebhookDelivery.FAILED, last_error=error)
    with schema_context(schema_name):
        WebhookDelivery.objects.filter(pk=delivery_id).update(**update_fields)
    return WebhookDelivery.FAILED


def _retry_webhook(task, delivery_id, schema_name, error, update_fields=None):
    update_fields = update_fields or {}
    if task.request.retries >= task.max_retries:
        update_fields.update(
            status=WebhookDelivery.FAILED,
            last_error=str(error)[:2000],
        )
        with schema_context(schema_name):
            WebhookDelivery.objects.filter(pk=delivery_id).update(**update_fields)
        logger.error("Entrega webhook %s agotó sus reintentos: %s", delivery_id, error)
        return WebhookDelivery.FAILED

    with schema_context(schema_name):
        WebhookDelivery.objects.filter(pk=delivery_id).update(
            **update_fields,
            last_error=str(error)[:2000],
        )
    raise task.retry(
        exc=error,
        countdown=min(60 * (2 ** task.request.retries), 3600),
    )


@shared_task
def mark_overdue_invoices():
    """
    Tarea programada para identificar facturas cuya fecha de vencimiento (due_date) 
    sea anterior a la fecha actual y su estado permita el vencimiento (Borrador o Emitida),
    actualizándolas al estado 'Vencida' (OVERDUE).
    """
    today = timezone.now().date()
    # Iteramos sobre todos los tenants (excluyendo el esquema público)
    tenants = Tenant.objects.exclude(schema_name='public')
    
    for tenant in tenants:
        with schema_context(tenant.schema_name):
            # Buscamos facturas vencidas (due_date < hoy) en estados no finales
            # Nota: Solo facturas 'Borrador' o 'Emitida' pueden pasar a 'Vencida'
            overdue_qs = Invoice.objects.filter(
                due_date__lt=today,
                status=Invoice.ISSUED
            )
            
            overdue_invoices = list(overdue_qs)
            count = len(overdue_invoices)
            if count > 0:
                # Actualización masiva eficiente sin disparar save() individual innecesario
                overdue_qs.update(status=Invoice.OVERDUE)
                
                # Registrar evento de auditoría de sistema para el tenant
                AuditEvent.objects.create(
                    action=AuditEvent.UPDATE,
                    entity="invoice",
                    summary=f"Automatización: {count} facturas marcadas como VENCIDAS.",
                    metadata={
                        "date_processed": str(today),
                        "affected_count": count
                    }
                )
                for invoice in overdue_invoices:
                    notify_users(
                        title=f"Factura vencida: {invoice.invoice_number}",
                        message=f"Tiene un saldo de {invoice.total} {invoice.currency} vencido desde {invoice.due_date}.",
                        link=f"/invoices/{invoice.pk}/",
                        level="danger",
                        entity="invoice",
                        entity_id=invoice.pk,
                        dedupe_key=f"invoice-overdue-{invoice.pk}",
                    )
    
    return f"Proceso de vencimiento completado para {tenants.count()} tenants."


def mark_expired_quotes_for_current_schema(today=None):
    today = today or timezone.localdate()
    return Quote.objects.filter(
        due_date__lt=today,
        status__in=[Quote.DRAFT, Quote.ACCEPTED],
    ).update(status=Quote.EXPIRED)


@shared_task
def mark_expired_quotes():
    """Marca cotizaciones vencidas en cada tenant y deja trazabilidad."""
    today = timezone.localdate()
    processed = 0
    for tenant in Tenant.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            expiring_quotes = list(
                Quote.objects.filter(
                    due_date__lt=today,
                    status__in=[Quote.DRAFT, Quote.ACCEPTED],
                )
            )
            count = mark_expired_quotes_for_current_schema(today)
            if count:
                AuditEvent.objects.create(
                    action=AuditEvent.UPDATE,
                    entity="quote",
                    summary=f"Automatización: {count} cotizaciones marcadas como vencidas.",
                    metadata={"date_processed": str(today), "affected_count": count},
                )
                processed += count
                for quote in expiring_quotes:
                    notify_users(
                        title=f"Cotización vencida: {quote.quote_number}",
                        message=f"La cotización venció el {quote.due_date} sin convertirse en factura.",
                        link=f"/quotes/{quote.pk}/",
                        level="warning",
                        entity="quote",
                        entity_id=quote.pk,
                        dedupe_key=f"quote-expired-{quote.pk}",
                    )
    return f"Cotizaciones vencidas actualizadas: {processed}."
