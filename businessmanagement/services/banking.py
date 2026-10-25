from __future__ import annotations
from businessmanagement.services.currency import convert_amount as _convert_amount

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
from django.utils import timezone
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
    _sync_payment_status,
    module_enabled_required,
    tenant_group_required,
    tenant_required,
)

from businessmanagement.forms import (
    BankStatementImportCSVForm,
    ReconciliationConfirmForm,
    ReconciliationManualForm,
)
from businessmanagement.services.imports import read_import_rows


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


def _rows_from_uploaded_file(uploaded, delimiter=","):
    """Usa el mismo lector seguro CSV/XLSX del pipeline genérico."""
    return read_import_rows(uploaded, delimiter)


@login_required
@tenant_required
@module_enabled_required("bank_statements")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_statement_import_csv(request):
    if request.method != "POST":
        form = BankStatementImportCSVForm()
        return render(
            request,
            "tenant/bank_statement_import.html",
            {"form": form, "page_title": "Importar extracto bancario"},
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

    extension = uploaded.name.lower().rsplit(".", 1)[-1]
    statement = BankStatement.objects.create(
        bank_account=bank_account,
        statement_date_from=None,
        statement_date_to=None,
        source=extension,
        imported_file=uploaded,
        created_by=request.user,
    )

    if extension == "csv" and not has_header:
        messages.error(
            request,
            "CSV sin encabezado no soportado en este MVP. Agrega header.",
        )
        statement.delete()
        return redirect("bank_statement_import_csv")

    try:
        rows = _rows_from_uploaded_file(uploaded, delimiter)
    except Exception as exc:
        statement.delete()
        messages.error(request, f"No fue posible leer el archivo: {exc}")
        return redirect("bank_statement_import_csv")

    imported_count = 0
    discarded_count = 0
    imported_dates = []
    for idx, row in enumerate(rows, start=1):
        date_val = row.get("date") or row.get("fecha")
        amount_val = row.get("amount") or row.get("monto")
        currency_val = (
            row.get("currency")
            or row.get("moneda")
            or bank_account.base_currency
        )
        desc_val = (
            row.get("description")
            or row.get("descripcion")
            or row.get("concept")
            or row.get("concepto")
            or row.get("detalle")
            or ""
        )
        external_id = (
            row.get("external_id")
            or row.get("reference")
            or row.get("referencia")
            or row.get("ref")
            or ""
        )

        tx_date = _parse_csv_date(date_val, statement_id=statement.pk, row_index=idx)
        if not tx_date:
            discarded_count += 1
            continue

        try:
            amount_dec = Decimal(str(amount_val).replace(",", "."))
        except Exception:
            discarded_count += 1
            continue
        if amount_dec == 0:
            discarded_count += 1
            continue

        currency = (currency_val or bank_account.base_currency).strip().upper()
        direction = "in" if amount_dec > 0 else "out"

        BankTransaction.objects.create(
            statement=statement,
            transaction_date=tx_date,
            description=(desc_val[:255] if desc_val else ""),
            concept=_normalize_text(desc_val)[:255],
            amount=abs(amount_dec),
            currency=currency,
            external_id=external_id[:120],
            direction=direction,
            status=BankTransaction.IMPORTED,
        )
        imported_count += 1
        imported_dates.append(tx_date)

    if imported_dates:
        statement.statement_date_from = min(imported_dates)
        statement.statement_date_to = max(imported_dates)
        statement.save(update_fields=["statement_date_from", "statement_date_to"])

    messages.success(
        request,
        f"Extracto {statement_name}: {imported_count} transacciones importadas, "
        f"{discarded_count} filas descartadas.",
    )
    if request.tenant.is_module_enabled("reconciliations"):
        return redirect("bank_transaction_suggestions", statement_id=statement.pk)
    return redirect("bank_statement_list")


@login_required
@tenant_required
@module_enabled_required("reconciliations")
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
            rec = Reconciliation.objects.filter(
                bank_transaction=tx, status=Reconciliation.PROPOSED
            ).first()
            if rec:
                rec.payment = p
                rec.financial_entry = fin_entry
                rec.match_confidence = int(score)
                rec.matched_concept = tx.concept or tx.description
                rec.save(update_fields=[
                    "payment", "financial_entry", "match_confidence",
                    "matched_concept",
                ])
            else:
                rec = Reconciliation.objects.create(
                    bank_transaction=tx,
                    payment=p,
                    financial_entry=fin_entry,
                    status=Reconciliation.PROPOSED,
                    match_confidence=int(score),
                    reconciliation_type="manual",
                    matched_concept=tx.concept or tx.description,
                )
            reconciliations.append(rec)

    reconciliation_map = {
        rec.bank_transaction_id: rec
        for rec in Reconciliation.objects.filter(bank_transaction__statement=statement)
        .exclude(status=Reconciliation.REJECTED)
        .select_related("payment", "financial_entry")
    }
    transaction_rows = [
        {
            "transaction": tx,
            "reconciliation": reconciliation_map.get(tx.pk),
            "manual_form": ReconciliationManualForm(prefix=f"tx-{tx.pk}"),
        }
        for tx in txs
    ]

    return render(
        request,
        "tenant/bank_transactions_suggestions.html",
        {
            "statement": statement,
            "transactions": txs,
            "reconciliations": reconciliations,
            "transaction_rows": transaction_rows,
        },
    )


@login_required
@tenant_required
@module_enabled_required("reconciliations")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def reconciliation_manual(request, transaction_id: int):
    bank_tx = BankTransaction.objects.select_related("statement").filter(
        pk=transaction_id
    ).first()
    if not bank_tx:
        messages.error(request, "Transacción bancaria no encontrada.")
        return redirect("bank_statement_list")
    if request.method != "POST":
        return redirect("bank_transaction_suggestions", statement_id=bank_tx.statement_id)

    form = ReconciliationManualForm(request.POST, prefix=f"tx-{bank_tx.pk}")
    if form.is_valid():
        payment = form.cleaned_data.get("payment")
        financial_entry = form.cleaned_data.get("financial_entry")
        if payment:
            financial_entry = payment.financial_entry
        rec, _ = Reconciliation.objects.update_or_create(
            bank_transaction=bank_tx,
            status=Reconciliation.PROPOSED,
            defaults={
                "payment": payment,
                "financial_entry": financial_entry,
                "match_confidence": 100,
                "reconciliation_type": "manual",
                "matched_concept": bank_tx.concept or bank_tx.description,
                "created_by": request.user,
            },
        )
        messages.success(request, "Enlace manual creado. Confírmelo para conciliar.")
    else:
        messages.error(request, "Seleccione un pago o movimiento válido.")
    return redirect("bank_transaction_suggestions", statement_id=bank_tx.statement_id)


def _confirm_reconciliation(rec, user):
    """Confirma una conciliación y materializa el pago cuando haga falta."""
    bank_tx = rec.bank_transaction
    if not rec.payment and rec.financial_entry:
        payment, _ = Payment.objects.get_or_create(
            financial_entry=rec.financial_entry,
            payment_date=bank_tx.transaction_date,
            amount=bank_tx.amount,
            currency=bank_tx.currency,
            defaults={
                "concept": bank_tx.description[:255] if bank_tx.description else "",
                "created_by": user,
            },
        )
        rec.payment = payment

    rec.status = Reconciliation.CONFIRMED
    rec.matched_at = timezone.now()
    rec.save(update_fields=["payment", "status", "matched_at"])
    bank_tx.status = BankTransaction.RECONCILED
    bank_tx.save(update_fields=["status"])

    if rec.financial_entry and rec.payment:
        paid_total = Decimal("0")
        for payment in rec.financial_entry.payments.all():
            paid_total += _convert_amount(
                payment.amount,
                payment.currency,
                rec.financial_entry.currency,
                payment.payment_date,
            )
        _sync_payment_status(rec.financial_entry, paid_total)
    return rec


@login_required
@tenant_required
@module_enabled_required("reconciliations")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def reconciliation_bulk_confirm(request, statement_id: int):
    if request.method != "POST":
        return redirect("bank_transaction_suggestions", statement_id=statement_id)
    ids = request.POST.getlist("reconciliation_ids")
    reconciliations = Reconciliation.objects.filter(
        pk__in=ids,
        bank_transaction__statement_id=statement_id,
        status=Reconciliation.PROPOSED,
    )
    confirmed = 0
    try:
        with transaction.atomic():
            for rec in reconciliations:
                _confirm_reconciliation(rec, request.user)
                confirmed += 1
    except ValueError as exc:
        messages.error(request, f"No se pudo convertir la moneda de un pago: {exc}")
        return redirect("bank_transaction_suggestions", statement_id=statement_id)
    messages.success(request, f"{confirmed} conciliaciones confirmadas.")
    return redirect("bank_transaction_suggestions", statement_id=statement_id)


@login_required
@tenant_required
@module_enabled_required("reconciliations")
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
        rec.bank_transaction.status = BankTransaction.REJECTED
        rec.bank_transaction.save(update_fields=["status"])
        messages.success(request, "Rechazado.")
        return redirect(
            "bank_transaction_suggestions",
            statement_id=rec.bank_transaction.statement_id,
        )

    if rec.status != Reconciliation.CONFIRMED:
        try:
            with transaction.atomic():
                _confirm_reconciliation(rec, request.user)
        except ValueError as exc:
            messages.error(request, f"No se pudo convertir la moneda del pago: {exc}")
            return redirect(
                "bank_transaction_suggestions",
                statement_id=rec.bank_transaction.statement_id,
            )

    messages.success(request, "Conciliación confirmada correctamente.")
    return redirect(
        "bank_transaction_suggestions",
        statement_id=rec.bank_transaction.statement_id,
    )
