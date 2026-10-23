from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenantdata", "0009_alter_employee_options_remove_invoice_tax_percentage_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quote",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Borrador"),
                    ("accepted", "Aceptada"),
                    ("converted", "Convertida"),
                    ("cancelled", "Cancelada"),
                    ("expired", "Vencida"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
    ]
