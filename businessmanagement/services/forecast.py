from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from .currency import convert_amount

from tenantdata.models import FinancialEntry


def budget_performance(budget):
    rows = []
    totals = defaultdict(lambda: {"budgeted": Decimal("0"), "actual": Decimal("0")})
    for line in budget.lines.select_related("category", "project").all():
        filters = {
            "business": budget.business,
            "entry_type": FinancialEntry.EXPENSE,
            "entry_date__range": (budget.period_start_date, budget.period_end_date),
            "currency": line.currency,
        }
        if line.category_id:
            filters["category_id"] = line.category_id
        if line.project_id:
            filters["project_id"] = line.project_id
        actual = FinancialEntry.objects.filter(**filters).exclude(
            status=FinancialEntry.CANCELLED
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        variance = line.budgeted_amount - actual
        consumption = (actual / line.budgeted_amount * 100) if line.budgeted_amount else Decimal("0")
        risk = "danger" if consumption > 100 else "warning" if consumption >= 80 else "success"
        rows.append({"line": line, "actual": actual, "variance": variance, "consumption": consumption, "risk": risk})
        totals[line.currency]["budgeted"] += line.budgeted_amount
        totals[line.currency]["actual"] += actual
    summaries = []
    for currency, values in sorted(totals.items()):
        values["variance"] = values["budgeted"] - values["actual"]
        summaries.append({"currency": currency, **values})
    return rows, summaries


def cashflow_forecast(business, start_date, end_date):
    entries = FinancialEntry.objects.filter(
        business=business,
        entry_type__in=[FinancialEntry.ACCOUNT_RECEIVABLE, FinancialEntry.ACCOUNT_PAYABLE],
        status__in=[FinancialEntry.PENDING, FinancialEntry.PARTIAL],
        due_date__range=(start_date, end_date),
    ).prefetch_related("payments")
    buckets = defaultdict(lambda: {"incoming": Decimal("0"), "outgoing": Decimal("0")})
    warnings = defaultdict(list)
    for entry in entries:
        try:
            paid = sum(
                (convert_amount(payment.amount, payment.currency, entry.currency, payment.payment_date)
                 for payment in entry.payments.all()), Decimal("0"),
            )
        except ValueError as exc:
            warnings[(entry.due_date.strftime("%Y-%m"), entry.currency)].append(
                f"Movimiento #{entry.pk}: {exc} Saldo excluido del cálculo."
            )
            continue
        remaining = max(entry.amount - paid, Decimal("0"))
        key = (entry.due_date.strftime("%Y-%m"), entry.currency)
        if entry.entry_type == FinancialEntry.ACCOUNT_RECEIVABLE:
            buckets[key]["incoming"] += remaining
        else:
            buckets[key]["outgoing"] += remaining
    rows = []
    for month, currency in sorted(buckets.keys() | warnings.keys()):
        values = buckets[(month, currency)]
        rows.append({"month": month, "currency": currency, "incoming": values["incoming"], "outgoing": values["outgoing"], "net": values["incoming"] - values["outgoing"], "warnings": warnings[(month, currency)]})
    return rows
