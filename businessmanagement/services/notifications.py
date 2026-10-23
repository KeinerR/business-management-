from django.contrib.auth import get_user_model
from django.db.models import Q

from tenantdata.models import Notification


FINANCE_GROUPS = ("Administrador de empresa", "Operador financiero")


def notify_users(*, title, message, link="", level=Notification.INFO, entity="", entity_id="", dedupe_key="", exclude_user=None, group_names=FINANCE_GROUPS):
    users = get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(groups__name__in=group_names)
    ).distinct()
    if exclude_user and getattr(exclude_user, "pk", None):
        users = users.exclude(pk=exclude_user.pk)

    notifications = []
    for user in users:
        defaults = {
            "title": title,
            "message": message,
            "link": link,
            "level": level,
            "entity": entity,
            "entity_id": str(entity_id or ""),
        }
        if dedupe_key:
            notification, _ = Notification.objects.update_or_create(
                recipient=user,
                dedupe_key=dedupe_key,
                defaults=defaults,
            )
        else:
            notification = Notification.objects.create(
                recipient=user, dedupe_key="", **defaults
            )
        notifications.append(notification)
    return notifications
