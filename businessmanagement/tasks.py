from celery import shared_task
from django.utils import timezone
from django_tenants.utils import schema_context
from tenantdata.models import Invoice, AuditEvent
from businessmanagement.models import Tenant

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
                status__in=[Invoice.DRAFT, Invoice.ISSUED]
            )
            
            count = overdue_qs.count()
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
    
    return f"Proceso de vencimiento completado para {tenants.count()} tenants."