from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from businessmanagement.services.webhooks import dispatch_webhook_event
from tenantdata.models import FinancialEntry, Invoice, Payment


@receiver(pre_save, sender=Invoice)
def remember_invoice_status(sender, instance, using, **kwargs):
    if instance.pk:
        instance._previous_status = (
            sender.objects.using(using)
            .filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )
    else:
        instance._previous_status = None


@receiver(post_save, sender=FinancialEntry)
def publish_financial_entry_created(sender, instance, created, **kwargs):
    if created:
        dispatch_webhook_event(
            "financial_entry.created",
            {
                "id": instance.pk,
                "concept": instance.concept,
                "amount": str(instance.amount),
                "currency": instance.currency,
                "entry_type": instance.entry_type,
                "status": instance.status,
                "entry_date": str(instance.entry_date),
            },
        )


@receiver(post_save, sender=Invoice)
def publish_invoice_events(sender, instance, created, **kwargs):
    payload = {
        "id": instance.pk,
        "invoice_number": instance.invoice_number,
        "status": instance.status,
        "total": str(instance.total),
        "currency": instance.currency,
    }
    if created:
        dispatch_webhook_event("invoice.created", payload)
    elif (
        getattr(instance, "_previous_status", None) != Invoice.PAID
        and instance.status == Invoice.PAID
    ):
        dispatch_webhook_event("invoice.paid", payload)


@receiver(post_save, sender=Payment)
def publish_payment_registered(sender, instance, created, **kwargs):
    if created:
        dispatch_webhook_event(
            "payment.registered",
            {
                "id": instance.pk,
                "financial_entry_id": instance.financial_entry_id,
                "payment_date": instance.payment_date.isoformat(),
                "amount": str(instance.amount),
                "currency": instance.currency,
            },
        )
