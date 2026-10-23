from django.db import DatabaseError

from tenantdata.models import Notification


def notification_context(request):
    tenant = getattr(request, "tenant", None)
    if (
        not request.user.is_authenticated
        or not tenant
        or getattr(tenant, "schema_name", "public") == "public"
    ):
        return {"unread_notification_count": 0, "recent_notifications": []}
    try:
        unread = Notification.objects.filter(
            recipient=request.user, is_read=False
        )
        return {
            "unread_notification_count": unread.count(),
            "recent_notifications": unread[:5],
        }
    except DatabaseError:
        return {"unread_notification_count": 0, "recent_notifications": []}
