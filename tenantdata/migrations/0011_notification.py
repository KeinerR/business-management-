from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenantdata", "0010_alter_quote_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.CharField(choices=[("info", "Información"), ("success", "Éxito"), ("warning", "Advertencia"), ("danger", "Crítica")], default="info", max_length=16)),
                ("title", models.CharField(max_length=160)),
                ("message", models.TextField()),
                ("link", models.CharField(blank=True, max_length=500)),
                ("entity", models.CharField(blank=True, max_length=80)),
                ("entity_id", models.CharField(blank=True, max_length=80)),
                ("dedupe_key", models.CharField(blank=True, max_length=190)),
                ("is_read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Notificación", "verbose_name_plural": "Notificaciones", "ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "is_read", "created_at"], name="tenantdata__recipie_20c3dc_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["entity", "entity_id"], name="tenantdata__entity_f743d8_idx"),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(condition=models.Q(("dedupe_key", ""), _negated=True), fields=("recipient", "dedupe_key"), name="unique_notification_dedupe_per_recipient"),
        ),
    ]
