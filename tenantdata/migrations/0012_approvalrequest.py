from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenantdata", "0011_notification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("quote", "Cotización"), ("expense", "Gasto")], max_length=30)),
                ("entity_id", models.PositiveBigIntegerField()),
                ("title", models.CharField(max_length=200)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("currency", models.CharField(blank=True, max_length=12)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("approved", "Aprobada"), ("rejected", "Rechazada"), ("cancelled", "Cancelada")], default="pending", max_length=16)),
                ("reason", models.TextField(blank=True)),
                ("decision_notes", models.TextField(blank=True)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="approval_requests", to="tenantdata.business")),
                ("requested_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_requests_created", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_requests_reviewed", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Solicitud de aprobación", "verbose_name_plural": "Solicitudes de aprobación", "ordering": ("-requested_at",)},
        ),
        migrations.AddIndex(model_name="approvalrequest", index=models.Index(fields=["status", "entity_type", "requested_at"], name="tenantdata__status_297f69_idx")),
        migrations.AddConstraint(model_name="approvalrequest", constraint=models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("entity_type", "entity_id"), name="unique_pending_approval_per_entity")),
    ]
