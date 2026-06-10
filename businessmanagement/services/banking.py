from __future__ import annotations

from csv import writer as csv_writer
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django_tenants.utils import schema_context

from tenantdata.models import (
    AuditEvent,
    BankAccount,
    BankStatement,
    BankTransaction,
    Payment,
    FinancialEntry,
    Reconciliation,
    ThirdParty,
    CurrencyRate,
)

from businessmanagement.views import (
    module_enabled_required,
    tenant_group_required,
    tenant_required,
)

from businessmanagement.forms import (
    BankStatementImportCSVForm,
    ReconciliationConfirmForm,
)


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _parse_csv_date(value: str, *, statement_id: int | None = None, row_index: int | None = None):
    """Parsea fecha tolerante para import bancario.

    - Soporta: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    - Retorna None si inválida.
    """
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else datetime.strptime(value, fmt).date()
        except Exception:
            continue

    if statement_id is not None:
        # No usamos logger todavía; mantenemos trazabilidad.
        print(f"[bank-import] invalid date discarded statement_id={statement_id} row_index={row_index} value={value!r}")
    return None


def _convert_amount(amount: Decimal, from_currency: str, to_currency: str, rate_date: date) -> Decimal:
    if from_currency == to_currency:
        return amount

    from_rate = CurrencyRate.objects.filter(currency=from_currency, rate_date=rate_date).first()
    to_rate = CurrencyRate.objects.filter(currency=to_currency, rate_date=rate_date).first()

    if not from_rate or not to_rate:
        raise ValueError(
            "No existe tasa de cambio para la fecha y monedas seleccionadas."
        )

    amount_local = amount * from_rate.rate_to_local
    return amount_local / to_rate.rate_to_local


def _compute_payment_match_score(payment: Payment, fin_entry: FinancialEntry, bank_tx: BankTransaction) -> int:
    score = 0

    delta_days = abs((payment.payment_date - bank_tx.transaction_date).days)
    if delta_days == 0:
        score += 50
    elif delta_days <= 1:
        score += 35
    elif delta_days <= 3:
        score += 20
    elif delta_days <= 7:
        score += 10

    if payment.currency == bank_tx.currency:
        if payment.amount == bank_tx.amount:
            score += 50
        else:
            try:
                diff = abs(payment.amount - bank_tx.amount)
                if diff <= 0.01:
                    score += 40
            except Exception:
                pass

    bank_concept = _normalize_text(bank_tx.concept or bank_tx.description)
    pay_concept = _normalize_text(payment.concept or "")
    fin_concept = _normalize_text(fin_entry.concept or "")

    if bank_concept and (
        bank_concept == pay_concept
        or bank_concept in pay_concept
        or pay_concept in bank_concept
    ):
        score += 25
    elif bank_concept and (bank_concept in fin_concept or fin_concept in bank_concept):
        score += 15

    return score


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_statement_import_csv(request):
    if request.method != "POST":
        form = BankStatementImportCSVForm()
        return render(
            request,
            "tenant/bank_statement_import.html",
            {"form": form, "page_title": "Importar extracto CSV"},
        )

    form = BankStatementImportCSVForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "tenant/bank_statement_import.html",
            {"form": form, "page_title": "Importar extracto CSV"},
        )

    bank_account = form.cleaned_data["bank_account"]
    uploaded = form.cleaned_data["file"]
    delimiter = form.cleaned_data["delimiter"]
    has_header = form.cleaned_data["has_header"]
    statement_name = form.cleaned_data["statement_name"] or f"Statement {date.today().isoformat()}"

    statement = BankStatement.objects.create(
        bank_account=bank_account,
        statement_date_from=None,
        statement_date_to=None,
        source="csv",
        imported_file=uploaded,
        created_by=request.user,
    )

    # decode
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("latin-1")

    import io
    import csv as csv_lib

    f = io.StringIO(text)
    if not has_header:
        messages.error(
            request,
            "CSV sin encabezado no soportado en este MVP. Agrega header.",
        )
        statement.delete()
        return redirect("bank_statement_import_csv")

    reader = csv_lib.DictReader(f, delimiter=delimiter)

    for idx, row in enumerate(reader, start=1):
        date_val = row.get("date") or row.get("fecha")
        amount_val = row.get("amount") or row.get("monto")
        currency_val = (
            row.get("currency")
            or row.get("moneda")
            or bank_account.base_currency
        )
        desc_val = (
            row.get("description")
            or row.get("concept")
            or row.get("detalle")
            or ""
        )
        external_id = (
            row.get("external_id")
            or row.get("reference")
            or row.get("ref")
            or ""
        )

        tx_date = _parse_csv_date(date_val, statement_id=statement.pk, row_index=idx)
        if not tx_date:
            continue

        try:
            amount_dec = Decimal(str(amount_val).replace(",", "."))
        except Exception:
            continue

        currency = (currency_val or bank_account.base_currency).strip().upper()

        BankTransaction.objects.create(
            statement=statement,
            transaction_date=tx_date,
            description=(desc_val[:255] if desc_val else ""),
            concept=_normalize_text(desc_val)[:255],
            amount=amount_dec,
            currency=currency,
            external_id=external_id[:120],
            direction="",
            status=BankTransaction.IMPORTED,
        )

    messages.success(request, f"Extracto importado: {statement_name}.")
    return redirect("bank_transaction_suggestions", statement_id=statement.pk)


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_transaction_suggestions(request, statement_id: int):
    statement = BankStatement.objects.filter(pk=statement_id).first()
    if not statement:
        messages.error(request, "Extracto no encontrado.")
        return redirect("dashboard")

    txs = statement.transactions.all().order_by("transaction_date", "created_at")

    reconciliations = []
    for tx in txs:
        from_date = tx.transaction_date - timedelta(days=3)
        to_date = tx.transaction_date + timedelta(days=3)

        payments_qs = Payment.objects.select_related(
            "financial_entry", "created_by"
        ).filter(
            payment_date__gte=from_date,
            payment_date__lte=to_date,
            currency=tx.currency,
        )

        best = []
        for p in payments_qs:
            fin_entry = p.financial_entry
            if not fin_entry:
                continue

            score = 0
            if p.amount == tx.amount:
                score += 70
            else:
                continue

            score += _compute_payment_match_score(p, fin_entry, tx)
            if score > 0:
                best.append((score, p, fin_entry))

        best.sort(key=lambda x: x[0], reverse=True)
        if best:
            score, p, fin_entry = best[0]
            rec, created = Reconciliation.objects.get_or_create(
                bank_transaction=tx,
                payment=p,
                financial_entry=fin_entry,
                status=Reconciliation.PROPOSED,
                defaults={
                    "match_confidence": int(score),
                    "reconciliation_type": "manual",
                    "matched_concept": tx.concept or tx.description,
                },
            )
            if not created:
                rec.match_confidence = int(score)
                rec.matched_concept = tx.concept or tx.description
                rec.save(update_fields=["match_confidence", "matched_concept"])
            reconciliations.append(rec)

    return render(
        request,
        "tenant/bank_transactions_suggestions.html",
        {
            "statement": statement,
            "transactions": txs,
            "reconciliations": reconciliations,
        },
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def reconciliation_confirm(request, rec_id: int):
    rec = Reconciliation.objects.filter(pk=rec_id).first()
    if not rec:
        messages.error(request, "Conciliación no encontrada.")
        return redirect("dashboard")

    form = ReconciliationConfirmForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Datos inválidos.")
        return redirect(
            "bank_transaction_suggestions",
            statement_id=rec.bank_transaction.statement_id,
        )

    action = form.cleaned_data["action"]

    if action == "reject":
        rec.status = Reconciliation.REJECTED
        rec.save(update_fields=["status"])
        messages.success(request, "Rechazado.")
        return redirect(
            "bank_transaction_suggestions",
            statement_id=rec.bank_transaction.statement_id,
        )

    if rec.status != Reconciliation.CONFIRMED:
        rec.status = Reconciliation.CONFIRMED
        rec.matched_at = date.today()
        rec.save(update_fields=["status", "matched_at"])

    if not rec.payment and rec.financial_entry:
        fin_entry = rec.financial_entry
        bank_tx = rec.bank_transaction
        with transaction.atomic():
            payment_qs = Payment.objects.filter(
                financial_entry=fin_entry,
                payment_date=bank_tx.transaction_date,
                amount=bank_tx.amount,
                currency=bank_tx.currency,
            )
            payment = payment_qs.first()
            if not payment:
                payment = Payment.objects.create(
                    financial_entry=fin_entry,
                    payment_date=bank_tx.transaction_date,
                    amount=bank_tx.amount,
                    currency=bank_tx.currency,
                    concept=bank_tx.description[:255] if bank_tx.description else "",
                    created_by=request.user,
                )
            rec.payment = payment
            rec.save(update_fields=["payment"])

    messages.success(request, "Conciliación confirmada correctamente.")
    return redirect(
        "bank_transaction_suggestions",
        statement_id=rec.bank_transaction.statement_id,
    )

