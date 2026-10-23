from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("businessmanagement", "0008_tenant_tenant_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="service_plan",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="tenant",
            name="service_status",
            field=models.CharField(
                choices=[
                    ("trial", "Prueba"),
                    ("active", "Activo"),
                    ("past_due", "Pago pendiente"),
                    ("suspended", "Suspendido"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="renewal_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="platform_notes",
            field=models.TextField(blank=True),
        ),
    ]
