from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = False

    dependencies = [
        ("tenantdata", "0005_financialentry_personal_financialcategory_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
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
                (
                    "payment_date",
                    models.DateField(),
                ),
                (
                    "amount",
                    models.DecimalField(max_digits=14, decimal_places=2),
                ),
                (
                    "currency",
                    models.CharField(
                        choices=[
                            ("COP", "COP"),
                            ("USD", "USD"),
                            ("EUR", "EUR"),
                            ("BINANCE", "Binance P2P"),
                        ],
                        max_length=12,
                    ),
                ),
                (
                    "concept",
                    models.CharField(max_length=255, blank=True),
                ),
                (
                    "notes",
                    models.TextField(blank=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payments_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "financial_entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="tenantdata.financialentry",
                    ),
                ),
            ],
            options={
                "verbose_name": "Pago",
                "verbose_name_plural": "Pagos",
                "ordering": ("-payment_date", "-created_at"),
                "indexes": [
                    models.Index(
                        fields=("payment_date", "currency"), name="payment_0f0c8b_idx"
                    ),
                    models.Index(
                        fields=("financial_entry", "payment_date"),
                        name="payment_4b8d8c_idx",
                    ),
                ],
            },
        ),
    ]
