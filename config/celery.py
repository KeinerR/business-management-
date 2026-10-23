import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('systemmanager')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

from celery.schedules import crontab

app.conf.beat_schedule = {
    "mark-overdue-invoices-daily": {
        "task": "businessmanagement.tasks.mark_overdue_invoices",
        "schedule": crontab(hour=1, minute=0),
    },
    "mark-expired-quotes-daily": {
        "task": "businessmanagement.tasks.mark_expired_quotes",
        "schedule": crontab(hour=1, minute=10),
    },
}

# NOTE: update_currency_rates task not implemented yet - disabled until implemented
# app.conf.beat_schedule = {
#     'update-currency-rates-daily': {
#         'task': 'businessmanagement.tasks.update_currency_rates',
#         'schedule': crontab(hour=3, minute=0),
#     },
# }
