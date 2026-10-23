import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenantdata", "0015_importbatch_confirmed_at_importbatch_rolled_back_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="APIIdempotencyRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=255)),
                ("request_fingerprint", models.CharField(max_length=64)),
                (
                    "response_status",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_idempotency_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Registro de idempotencia API",
                "verbose_name_plural": "Registros de idempotencia API",
            },
        ),
        migrations.CreateModel(
            name="WebhookEndpoint",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("url", models.URLField(max_length=500)),
                ("secret", models.CharField(max_length=128)),
                ("event_types", models.JSONField(default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="webhook_endpoints_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Endpoint webhook",
                "verbose_name_plural": "Endpoints webhook",
                "ordering": ("name", "id"),
            },
        ),
        migrations.CreateModel(
            name="WebhookDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event", models.CharField(max_length=80)),
                ("target_url", models.URLField(max_length=500)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("delivered", "Entregada"),
                            ("failed", "Fallida"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "response_status",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("response_body", models.TextField(blank=True)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "endpoint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deliveries",
                        to="tenantdata.webhookendpoint",
                    ),
                ),
            ],
            options={
                "verbose_name": "Entrega de webhook",
                "verbose_name_plural": "Entregas de webhooks",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="apiidempotencyrecord",
            constraint=models.UniqueConstraint(
                fields=("user", "key"),
                name="unique_api_idempotency_key_per_user",
            ),
        ),
        migrations.AddIndex(
            model_name="apiidempotencyrecord",
            index=models.Index(fields=["created_at"], name="api_idem_created_idx"),
        ),
        migrations.AddIndex(
            model_name="webhookdelivery",
            index=models.Index(
                fields=["status", "created_at"], name="webhook_status_date_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="webhookdelivery",
            index=models.Index(
                fields=["event", "created_at"], name="webhook_event_date_idx"
            ),
        ),
    ]
