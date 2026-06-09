import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('systemmanager')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Periodic schedule: run update_currency_rates every day at 03:00 UTC by default
from celery.schedules import crontab
app.conf.beat_schedule = {
    'update-currency-rates-daily': {
        'task': 'businessmanagement.tasks.update_currency_rates',
        'schedule': crontab(hour=3, minute=0),
    },
}
