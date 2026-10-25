from django.db import DatabaseError

from tenantdata.models import Notification


def notification_context(request):
    tenant = getattr(request, "tenant", None)
    is_tenant_admin = False
    is_financial_operator = False
    if (
        request.user.is_authenticated
        and tenant
        and getattr(tenant, "schema_name", "public") != "public"
    ):
        group_names = set(request.user.groups.values_list("name", flat=True))
        is_tenant_admin = "Administrador de empresa" in group_names
        is_financial_operator = "Operador financiero" in group_names
    if (
        not request.user.is_authenticated
        or not tenant
        or getattr(tenant, "schema_name", "public") == "public"
        or not tenant.is_module_enabled("notifications")
    ):
        return {
            "unread_notification_count": 0,
            "recent_notifications": [],
            "is_tenant_admin": is_tenant_admin,
            "is_financial_operator": is_financial_operator,
        }
    try:
        unread = Notification.objects.filter(
            recipient=request.user, is_read=False
        )
        return {
            "unread_notification_count": unread.count(),
            "recent_notifications": unread[:5],
            "is_tenant_admin": is_tenant_admin,
            "is_financial_operator": is_financial_operator,
        }
    except DatabaseError:
        return {
            "unread_notification_count": 0,
            "recent_notifications": [],
            "is_tenant_admin": is_tenant_admin,
            "is_financial_operator": is_financial_operator,
        }
