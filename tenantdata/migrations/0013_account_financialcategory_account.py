from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("tenantdata", "0012_approvalrequest")]

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20)),
                ("name", models.CharField(max_length=180)),
                ("account_type", models.CharField(choices=[("asset", "Activo"), ("liability", "Pasivo"), ("equity", "Patrimonio"), ("income", "Ingresos"), ("expense", "Gastos"), ("cost", "Costos")], max_length=20)),
                ("nature", models.CharField(choices=[("debit", "Débito"), ("credit", "Crédito")], max_length=10)),
                ("accepts_entries", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accounts", to="tenantdata.business")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="tenantdata.account")),
            ],
            options={"verbose_name": "Cuenta contable", "verbose_name_plural": "Plan contable", "ordering": ("code",)},
        ),
        migrations.AddField(
            model_name="financialcategory",
            name="account",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="financial_categories", to="tenantdata.account"),
        ),
        migrations.AddIndex(model_name="account", index=models.Index(fields=["account_type", "is_active"], name="tenantdata__account_25b889_idx")),
        migrations.AddConstraint(model_name="account", constraint=models.UniqueConstraint(fields=("business", "code"), name="unique_account_code_per_business")),
    ]
