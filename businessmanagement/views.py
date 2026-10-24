from businessmanagement.services.currency import convert_amount as _convert_amount
from csv import writer as csv_writer
from datetime import date, timedelta
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.db import connection, transaction, OperationalError, ProgrammingError
from django.db.models import Count, Sum, Q
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST
import io
import csv
import logging
from django_tenants.utils import schema_context
from functools import wraps
from decimal import Decimal, InvalidOperation

from tenantdata.models import (
    AuditEvent,
    Business,
    CurrencyRate,
    Employee,
    FinancialEntry,
    ThirdParty,
    Invoice,
    InvoiceItem,
    Project,
    FinancialCategory,
    Payment,
    BankAccount,
    BankStatement,
    BankTransaction,
    Reconciliation,
    Quote,
    CreditNote,
    Budget,
    BudgetLine,
    TaxRule,
    CreditNoteItem,
    ImportBatch,
    ImportedRecord,
    DebitNote,
    QuoteItem,
    Notification,
    ApprovalRequest,
    Account,
    Document,
    DocumentVersion,
)


from .forms import (
    CurrencyRateForm,
    EmployeeCreateForm,
    EmployeeEditForm,
    FinancialEntryForm,
    PlatformTenantCreateForm,
    PlatformTenantEditForm,
    TenantGroupForm,
    TenantUserForm,
    ThirdPartyForm,
    InvoiceForm,
    TaxRuleForm,
    BudgetForm,
    BudgetLineFormSet,
    QuoteForm,
    CreditNoteForm,
    DebitNoteForm,
    PaymentForm,
    ProjectForm,
    FinancialCategoryForm,
    BankStatementImportCSVForm,
    ReconciliationConfirmForm,
    GenericImportUploadForm,
    BankAccountForm,
    ApprovalRequestForm,
    ApprovalDecisionForm,
    AccountForm,
    DocumentCreateForm,
    DocumentVersionForm,
)
from .models import Domain, Tenant
from .services.notifications import notify_users
from .services.accounting import seed_puc_starter
from .services.forecast import budget_performance, cashflow_forecast
from .services.document_management import add_document_version
from .services.imports import confirm_batch, preview_batch, read_import_rows, rollback_batch
from .modules import AVAILABLE_MODULES, MODULES_INDIVIDUAL, MODULES_BUSINESS, MODULE_GROUPS

logger = logging.getLogger(__name__)

# Create your views here.


def is_tenant_request(request):
    current_tenant = getattr(request, "tenant", None)
    return (
        connection.schema_name != settings.PUBLIC_SCHEMA_NAME
        and current_tenant
        and getattr(current_tenant, "schema_name", settings.PUBLIC_SCHEMA_NAME)
        != settings.PUBLIC_SCHEMA_NAME
    )


def tenant_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_tenant_request(request):
            messages.error(
                request,
                "Esta seccion solo esta disponible desde el dominio de una empresa.",
            )
            if request.user.is_authenticated and (
                request.user.is_staff or request.user.is_superuser
            ):
                return redirect("platform_dashboard")
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return wrapper


def redirect_platform_managed_section(request):
    messages.info(
        request,
        "Las empresas y sus tenants se administran desde el panel principal de la plataforma.",
    )
    if (
        request.user.is_authenticated
        and (request.user.is_staff or request.user.is_superuser)
        and not is_tenant_request(request)
    ):
        return redirect("platform_dashboard")
    return redirect("dashboard")


def record_audit_event(request, action, entity, summary, entity_id="", metadata=None):
    AuditEvent.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id or ""),
        summary=summary,
        metadata=metadata or {},
    )


def module_enabled_required(module_name: str):
    """Bloquea vistas si el tenant no tiene habilitado el módulo."""
    # Validación preventiva para asegurar consistencia con el registro centralizado
    valid_modules = [m[0] for m in AVAILABLE_MODULES]
    if module_name not in valid_modules:
        raise ValueError(f"Módulo '{module_name}' no registrado en modules.AVAILABLE_MODULES")

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            tenant = getattr(request, "tenant", None)
            if not tenant or not tenant.is_module_enabled(module_name):
                messages.error(
                    request,
                    "Este módulo no está habilitado para la empresa actual.",
                )
                return redirect("dashboard")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def has_tenant_group(user, group_name):
    return user.groups.filter(name=group_name).exists()


def tenant_group_required(*group_names):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Los superusuarios siempre tienen acceso
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            if not any(has_tenant_group(request.user, name) for name in group_names):
                messages.error(
                    request, "No tienes permiso para acceder a esta sección."
                )
                return redirect("dashboard")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def resolve_period_range(period):
    today = date.today()
    if period == "monthly":
        return date(today.year, today.month, 1), today
    if period == "annual":
        return date(today.year, 1, 1), today
    if period == "semestral":
        return today - timedelta(days=183), today
    return None, None


def ensure_default_tenant_groups():
    default_groups = ("Administrador de empresa", "Operador financiero", "Solo lectura")
    for group_name in default_groups:
        Group.objects.get_or_create(name=group_name)


def platform_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if is_tenant_request(request):
            messages.error(
                request,
                "El panel de plataforma solo esta disponible desde el dominio public.",
            )
            return redirect("dashboard")
        if not request.user.is_staff and not request.user.is_superuser:
            messages.error(
                request, "Necesitas permisos de administrador de plataforma."
            )
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return wrapper


def home(request):
    if request.user.is_authenticated:
        if is_tenant_request(request):
            return redirect("dashboard")
        if request.user.is_staff or request.user.is_superuser:
            return redirect("platform_dashboard")
    return render(request, "guest/home.html")


def login_view(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if request.user.is_authenticated:
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        if not is_tenant_request(request) and (
            request.user.is_staff or request.user.is_superuser
        ):
            return redirect("platform_dashboard")
        if not is_tenant_request(request):
            return redirect("home")
        return redirect("dashboard")

    form = AuthenticationForm(request, data=request.POST or None)
    current_tenant = getattr(request, "tenant", None)

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()

            if (
                current_tenant
                and getattr(current_tenant, "schema_name", "public") != "public"
            ):
                try:
                    employee_profile = user.employee_profile
                except ObjectDoesNotExist:
                    employee_profile = None

                if employee_profile is None and not (
                    user.is_staff or user.is_superuser
                ):
                    form.add_error(
                        None, "Este usuario no pertenece a la empresa actual."
                    )
                else:
                    login(request, user)
                    messages.success(request, f"Bienvenido, {user.get_username()}")
                    if next_url and url_has_allowed_host_and_scheme(
                        next_url,
                        allowed_hosts={request.get_host()},
                        require_https=request.is_secure(),
                    ):
                        return redirect(next_url)
                    return redirect("dashboard")
            else:
                if user.is_staff or user.is_superuser:
                    login(request, user)
                    messages.success(request, f"Bienvenido, {user.get_username()}")
                    if next_url and url_has_allowed_host_and_scheme(
                        next_url,
                        allowed_hosts={request.get_host()},
                        require_https=request.is_secure(),
                    ):
                        return redirect(next_url)
                    return redirect("platform_dashboard")
                form.add_error(
                    None, "El acceso debe hacerse desde el dominio de una empresa."
                )

    return render(request, "guest/login.html", {"form": form, "next": next_url})


@login_required
def dashboard_view(request):
    if not is_tenant_request(request):
        if request.user.is_staff or request.user.is_superuser:
            return redirect("platform_dashboard")
        messages.error(
            request,
            "El dashboard solo esta disponible desde el dominio de una empresa.",
        )
        return redirect("login")
    tenant = request.tenant
    enabled_modules = set(tenant.enabled_modules or [])
    business = Business.objects.first()
    employee_count = Employee.objects.count() if "employees" in enabled_modules else 0
    user_count = get_user_model().objects.count() if "users" in enabled_modules else 0
    third_party_count = (
        ThirdParty.objects.filter(is_active=True).count()
        if "third_parties" in enabled_modules
        else 0
    )
    pending_count = FinancialEntry.objects.filter(
        status__in=[FinancialEntry.PENDING, FinancialEntry.PARTIAL]
    ).count()
    totals_by_type = FinancialEntry.objects.values("entry_type").annotate(
        total=Sum("amount")
    )
    totals = {row["entry_type"]: row["total"] or 0 for row in totals_by_type}
    latest_entries = FinancialEntry.objects.select_related(
        "third_party", "created_by", "project", "category"
    )[:6]
    latest_audit_events = AuditEvent.objects.select_related("actor")[:6]
    latest_rates = CurrencyRate.objects.order_by("-rate_date", "currency")[:3]

    today = date.today()
    current_month_start = date(today.year, today.month, 1)
    current_month_entries = FinancialEntry.objects.filter(
        entry_date__gte=current_month_start,
        entry_date__lte=today,
        currency="COP",
    )
    income_current_month = current_month_entries.filter(
        entry_type=FinancialEntry.INCOME
    ).aggregate(Sum("amount"))["amount__sum"] or Decimal("0.00")
    expense_current_month = current_month_entries.filter(
        entry_type=FinancialEntry.EXPENSE
    ).aggregate(Sum("amount"))["amount__sum"] or Decimal("0.00")
    monthly_max = max(income_current_month, expense_current_month, Decimal("1.00"))

    return render(
        request,
        "dashboard.html",
        {
            "business": business,
            "tenant_type": tenant.tenant_type,
            "enabled_modules": enabled_modules,
            "employee_count": employee_count,
            "user_count": user_count,
            "third_party_count": third_party_count,
            "pending_count": pending_count,
            "income_total": totals.get(FinancialEntry.INCOME, 0),
            "expense_total": totals.get(FinancialEntry.EXPENSE, 0),
            "expense_total_neg": -totals.get(FinancialEntry.EXPENSE, 0),
            "receivable_total": totals.get(FinancialEntry.ACCOUNT_RECEIVABLE, 0),
            "payable_total": totals.get(FinancialEntry.ACCOUNT_PAYABLE, 0),
            "payable_total_neg": -totals.get(FinancialEntry.ACCOUNT_PAYABLE, 0),
            "latest_entries": latest_entries,
            "latest_audit_events": latest_audit_events,
            "latest_rates": latest_rates,
            "income_current_month": income_current_month,
            "expense_current_month": expense_current_month,
            "income_current_month_percent": int(income_current_month * 100 / monthly_max),
            "expense_current_month_percent": int(expense_current_month * 100 / monthly_max),
        },
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def module_settings(request):
    """
    Vista para que administradores vean detalles técnicos de sus módulos habilitados.
    """
    tenant = getattr(request, "tenant", None)
    enabled_modules_list = getattr(tenant, "enabled_modules", [])
    module_labels = dict(AVAILABLE_MODULES)
    
    # Mapa inverso de grupos para búsqueda rápida en el template
    module_to_group = {}
    for group_name, mods in MODULE_GROUPS.items():
        for m in mods:
            module_to_group[m] = group_name

    details = []
    for mod_id in enabled_modules_list:
        details.append({
            "key": mod_id,
            "label": module_labels.get(mod_id, mod_id),
            "group": module_to_group.get(mod_id, "Sin categoría"),
            "is_business": mod_id in MODULES_BUSINESS,
            "is_individual": mod_id in MODULES_INDIVIDUAL,
        })

    return render(
        request,
        "tenant/module_settings.html",
        {"module_details": details, "page_title": "Ajustes de Módulos"},
    )


@login_required
@tenant_required
@module_enabled_required("budget")
def budget_list(request):
    budgets = Budget.objects.filter(business=Business.objects.first()).order_by("-period_start_date")
    status = request.GET.get("status")
    if status:
        budgets = budgets.filter(status=status)

    page_num = request.GET.get("page", 1)
    paginator = Paginator(budgets, 25)
    budgets_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/budget_list.html",
        {
            "budgets": budgets_page,
            "status_choices": Budget.STATUS_CHOICES,
            "selected_status": status or "",
            "page_title": "Listado de Presupuestos",
        },
    )


@login_required
@tenant_required
@module_enabled_required("budget")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def budget_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(request, "Primero debes crear la empresa asociada a este tenant.")
        return redirect("dashboard")

    if request.method == "POST":
        form = BudgetForm(request.POST)
        formset = BudgetLineFormSet(request.POST, instance=Budget())
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    budget = form.save(commit=False)
                    budget.business = business
                    budget.created_by = request.user
                    budget.save()

                    formset.instance = budget
                    formset.save()

                    budget.calculate_total_budgeted_amount() # Recalculate total after lines are saved
                    budget.save(update_fields=['total_budgeted_amount'])

                    record_audit_event(
                        request, AuditEvent.CREATE, "budget",
                        f"Presupuesto creado: {budget.name}",
                        entity_id=budget.pk
                    )
                    messages.success(request, "Presupuesto creado correctamente.")
                    return redirect("budget_detail", budget_id=budget.pk)
            except Exception as e:
                messages.error(request, f"Error al crear el presupuesto: {str(e)}")
        else:
            messages.error(request, "Por favor, corrija los errores en el formulario.")
    else:
        form = BudgetForm()
        formset = BudgetLineFormSet(instance=Budget())

    return render(request, "tenant/budget_form.html", {
        "form": form,
        "formset": formset,
        "page_title": "Crear Nuevo Presupuesto",
        "business": business,
    })


@login_required
@tenant_required
@module_enabled_required("budget")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def budget_edit(request, budget_id):
    budget = Budget.objects.filter(pk=budget_id, business=Business.objects.first()).first()
    if not budget:
        messages.error(request, "Presupuesto no encontrado.")
        return redirect("budget_list")

    if request.method == "POST":
        form = BudgetForm(request.POST, instance=budget)
        formset = BudgetLineFormSet(request.POST, instance=budget)
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    budget = form.save()
                    formset.save()

                    budget.calculate_total_budgeted_amount() # Recalculate total after lines are saved
                    budget.save(update_fields=['total_budgeted_amount'])

                    record_audit_event(
                        request, AuditEvent.UPDATE, "budget",
                        f"Presupuesto actualizado: {budget.name}",
                        entity_id=budget.pk
                    )
                    messages.success(request, "Presupuesto actualizado correctamente.")
                    return redirect("budget_detail", budget_id=budget.pk)
            except Exception as e:
                messages.error(request, f"Error al actualizar el presupuesto: {str(e)}")
        else:
            messages.error(request, "Por favor, corrija los errores en el formulario.")
    else:
        form = BudgetForm(instance=budget)
        formset = BudgetLineFormSet(instance=budget)

    return render(request, "tenant/budget_form.html", {
        "form": form,
        "formset": formset,
        "page_title": f"Editar Presupuesto: {budget.name}",
        "budget": budget,
        "business": budget.business,
    })


@login_required
@tenant_required
@module_enabled_required("budget")
def budget_detail(request, budget_id):
    budget = Budget.objects.filter(pk=budget_id, business=Business.objects.first()).first()
    if not budget:
        messages.error(request, "Presupuesto no encontrado.")
        return redirect("budget_list")
    
    performance_rows, performance_totals = budget_performance(budget)
    forecast_rows = cashflow_forecast(
        budget.business, budget.period_start_date, budget.period_end_date
    )
    return render(request, "tenant/budget_detail.html", {
        "budget": budget,
        "page_title": f"Detalle Presupuesto: {budget.name}",
        "performance_rows": performance_rows,
        "performance_totals": performance_totals,
        "forecast_rows": forecast_rows,
    })


@login_required
@tenant_required
@module_enabled_required("budget")
def forecast_dashboard(request):
    business = Business.objects.first()
    today = date.today()
    try:
        days = min(max(int(request.GET.get("days", 90)), 30), 365)
    except (TypeError, ValueError):
        days = 90
    end_date = today + timedelta(days=days)
    rows = cashflow_forecast(business, today, end_date) if business else []
    return render(request, "tenant/forecast_dashboard.html", {"forecast_rows": rows, "start_date": today, "end_date": end_date, "days": days})


@login_required
@tenant_required
@module_enabled_required("documents")
def document_list(request):
    documents = Document.objects.select_related("created_by", "business").prefetch_related("versions").filter(
        business=Business.objects.first()
    )
    status = request.GET.get("status", Document.ACTIVE)
    document_type = request.GET.get("type", "")
    query = request.GET.get("q", "").strip()
    if status in dict(Document.STATUS_CHOICES):
        documents = documents.filter(status=status)
    if document_type in dict(Document.TYPE_CHOICES):
        documents = documents.filter(document_type=document_type)
    if query:
        documents = documents.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(tags__icontains=query))
    return render(request, "tenant/document_list.html", {
        "documents": Paginator(documents, 25).get_page(request.GET.get("page", 1)),
        "status_choices": Document.STATUS_CHOICES,
        "type_choices": Document.TYPE_CHOICES,
        "selected_status": status,
        "selected_type": document_type,
        "query": query,
    })


@login_required
@tenant_required
@module_enabled_required("documents")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def document_create(request):
    business = Business.objects.first()
    if not business:
        messages.error(request, "Primero debes crear la empresa asociada al tenant.")
        return redirect("dashboard")
    form = DocumentCreateForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            document = form.save(commit=False)
            document.business = business
            document.created_by = request.user
            document.save()
            version = add_document_version(document, form.cleaned_data["file"], request.user, form.cleaned_data["version_notes"])
            record_audit_event(request, AuditEvent.CREATE, "document", f"Documento creado: {document.title} (v{version.version})", document.pk)
        messages.success(request, "Documento y primera versión guardados.")
        return redirect("document_detail", document_id=document.pk)
    return render(request, "tenant/document_form.html", {"form": form})


@login_required
@tenant_required
@module_enabled_required("documents")
def document_detail(request, document_id):
    document = Document.objects.select_related("created_by").prefetch_related("versions__uploaded_by").filter(
        pk=document_id, business=Business.objects.first()
    ).first()
    if not document:
        raise Http404("Documento no encontrado")
    return render(request, "tenant/document_detail.html", {"document": document, "version_form": DocumentVersionForm()})


@login_required
@tenant_required
@module_enabled_required("documents")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def document_add_version(request, document_id):
    document = Document.objects.filter(pk=document_id, business=Business.objects.first(), status=Document.ACTIVE).first()
    if not document:
        messages.error(request, "El documento no existe o está archivado.")
        return redirect("document_list")
    form = DocumentVersionForm(request.POST, request.FILES)
    if form.is_valid():
        version = add_document_version(document, form.cleaned_data["file"], request.user, form.cleaned_data["notes"])
        record_audit_event(request, AuditEvent.UPDATE, "document", f"Nueva versión de {document.title}: v{version.version}", document.pk)
        messages.success(request, f"Versión {version.version} agregada sin alterar las anteriores.")
    else:
        messages.error(request, "No se pudo cargar la versión: " + " ".join(sum(form.errors.values(), [])))
    return redirect("document_detail", document_id=document.pk)


@login_required
@tenant_required
@module_enabled_required("documents")
def document_download(request, document_id, version_id):
    version = DocumentVersion.objects.select_related("document").filter(
        pk=version_id, document_id=document_id, document__business=Business.objects.first()
    ).first()
    if not version or not version.file:
        raise Http404("Archivo no encontrado")
    try:
        response = FileResponse(version.file.open("rb"), content_type=version.mime_type or "application/octet-stream")
    except FileNotFoundError as exc:
        raise Http404("El archivo físico no está disponible") from exc
    response["Content-Disposition"] = f'attachment; filename="{version.original_name.replace(chr(34), "")}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@tenant_required
@module_enabled_required("documents")
@tenant_group_required("Administrador de empresa")
@require_POST
def document_archive(request, document_id):
    document = Document.objects.filter(pk=document_id, business=Business.objects.first()).first()
    if not document:
        raise Http404("Documento no encontrado")
    document.status = Document.ARCHIVED if document.status == Document.ACTIVE else Document.ACTIVE
    document.save(update_fields=["status", "updated_at"])
    record_audit_event(request, AuditEvent.UPDATE, "document", f"Documento {document.get_status_display().lower()}: {document.title}", document.pk)
    messages.success(request, f"Documento marcado como {document.get_status_display().lower()}.")
    return redirect("document_detail", document_id=document.pk)


@login_required
@platform_required
def platform_dashboard(request):
    tenants = Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
    tenant_count = tenants.count()
    active_tenant_count = tenants.filter(is_active=True).count()
    inactive_tenant_count = tenant_count - active_tenant_count
    attention_tenant_count = tenants.filter(
        Q(renewal_date__lte=timezone.localdate() + timedelta(days=30))
        | Q(service_status__in=(Tenant.SERVICE_PAST_DUE, Tenant.SERVICE_SUSPENDED))
    ).count()
    domain_count = Domain.objects.exclude(tenant__schema_name=settings.PUBLIC_SCHEMA_NAME).count()
    primary_domains = Domain.objects.filter(is_primary=True).exclude(
        tenant__schema_name=settings.PUBLIC_SCHEMA_NAME
    )
    public_domain_count = Domain.objects.filter(
        tenant__schema_name=settings.PUBLIC_SCHEMA_NAME
    ).count()
    tenant_snapshots = []
    for tenant in tenants.prefetch_related("domains").order_by("-created_on")[:6]:
        tenant_snapshots.append(_platform_tenant_snapshot(tenant))
    return render(
        request,
        "platform/dashboard.html",
        {
            "tenant_count": tenant_count,
            "active_tenant_count": active_tenant_count,
            "inactive_tenant_count": inactive_tenant_count,
            "attention_tenant_count": attention_tenant_count,
            "domain_count": domain_count,
            "public_domain_count": public_domain_count,
            "primary_domains": primary_domains[:6],
            "tenant_snapshots": tenant_snapshots,
        },
    )


@login_required
@platform_required
def platform_tenant_list(request):
    queryset = Tenant.objects.exclude(
        schema_name=settings.PUBLIC_SCHEMA_NAME
    ).prefetch_related("domains").order_by("name")
    search = request.GET.get("q", "").strip()
    service_status = request.GET.get("status", "").strip()
    renewal_filter = request.GET.get("renewal", "").strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(schema_name__icontains=search)
            | Q(service_plan__icontains=search)
            | Q(domains__domain__icontains=search)
        ).distinct()
    if service_status in dict(Tenant.SERVICE_STATUS_CHOICES):
        queryset = queryset.filter(service_status=service_status)
    if renewal_filter == "soon":
        queryset = queryset.filter(
            renewal_date__gte=timezone.localdate(),
            renewal_date__lte=timezone.localdate() + timedelta(days=30),
        )
    elif renewal_filter == "overdue":
        queryset = queryset.filter(renewal_date__lt=timezone.localdate())

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    tenant_cards = [
        _platform_tenant_snapshot(tenant)
        for tenant in page_obj.object_list
    ]
    return render(
        request,
        "platform/tenant_list.html",
        {
            "tenant_cards": tenant_cards,
            "page_obj": page_obj,
            "search": search,
            "selected_status": service_status,
            "selected_renewal": renewal_filter,
            "status_choices": Tenant.SERVICE_STATUS_CHOICES,
            "today": timezone.localdate(),
        },
    )


def _platform_tenant_snapshot(tenant):
    snapshot = {
        "tenant": tenant,
        "business": None,
        "employee_count": None,
        "user_count": None,
        "entry_count": None,
        "invoice_count": None,
        "latest_activity": None,
        "schema_ready": True,
    }
    try:
        with schema_context(tenant.schema_name):
            snapshot["business"] = Business.objects.first()
            snapshot["employee_count"] = Employee.objects.count()
            snapshot["user_count"] = get_user_model().objects.count()
            snapshot["entry_count"] = FinancialEntry.objects.count()
            snapshot["invoice_count"] = Invoice.objects.count()
            snapshot["latest_activity"] = AuditEvent.objects.first()
    except (OperationalError, ProgrammingError):
        snapshot["schema_ready"] = False
    return snapshot


@login_required
@platform_required
def platform_tenant_detail(request, tenant_id):
    tenant = (
        Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        .prefetch_related("domains")
        .filter(pk=tenant_id)
        .first()
    )
    if not tenant:
        raise Http404("Tenant no encontrado")
    snapshot = _platform_tenant_snapshot(tenant)
    recent_activity = []
    tenant_admins = []
    if snapshot["schema_ready"]:
        try:
            with schema_context(tenant.schema_name):
                recent_activity = list(AuditEvent.objects.select_related("actor")[:12])
                tenant_admins = list(
                    get_user_model().objects.filter(is_superuser=True).order_by("username")[:10]
                )
        except (OperationalError, ProgrammingError):
            snapshot["schema_ready"] = False
    return render(
        request,
        "platform/tenant_detail.html",
        {
            **snapshot,
            "recent_activity": recent_activity,
            "tenant_admins": tenant_admins,
            "enabled_module_labels": [
                label
                for value, label in AVAILABLE_MODULES
                if value in tenant.enabled_modules
            ],
        },
    )


@login_required
@platform_required
@require_POST
def platform_tenant_toggle_active(request, tenant_id):
    tenant = (
        Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        .filter(pk=tenant_id)
        .first()
    )
    if not tenant:
        raise Http404("Tenant no encontrado")
    tenant.is_active = not tenant.is_active
    if tenant.is_active and tenant.service_status == Tenant.SERVICE_SUSPENDED:
        tenant.service_status = Tenant.SERVICE_ACTIVE
    elif not tenant.is_active and tenant.service_status in (
        Tenant.SERVICE_ACTIVE,
        Tenant.SERVICE_TRIAL,
    ):
        tenant.service_status = Tenant.SERVICE_SUSPENDED
    tenant.save(update_fields=("is_active", "service_status"))
    state = "activado" if tenant.is_active else "suspendido"
    messages.success(request, f"El acceso de {tenant.name} fue {state}.")
    return redirect("platform_tenant_detail", tenant_id=tenant.pk)


@login_required
@platform_required
def platform_tenant_create(request):
    form = PlatformTenantCreateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        cleaned_data = form.cleaned_data
        tenant = form.save()
        Domain.objects.create(
            domain=cleaned_data["domain"],
            tenant=tenant,
            is_primary=True,
        )

        with schema_context(tenant.schema_name):
            ensure_default_tenant_groups()
            business = Business.objects.create(
                name_business_owner=cleaned_data["name_business_owner"],
                last_name_business_owner=cleaned_data["last_name_business_owner"],
                business_name=cleaned_data["business_name"],
                business_phone=cleaned_data["business_phone"],
                business_email=cleaned_data["business_email"],
                business_address=cleaned_data["business_address"],
                description=cleaned_data["description"],
            )
            user = get_user_model().objects.create_user(
                username=cleaned_data["admin_username"],
                password=cleaned_data["admin_password"],
                email=cleaned_data["admin_email"],
                first_name=cleaned_data["admin_first_name"],
                last_name=cleaned_data["admin_last_name"],
                is_staff=True,
                is_superuser=True,
            )
            Employee.objects.create(
                user=user,
                first_name=cleaned_data["admin_first_name"],
                last_name=cleaned_data["admin_last_name"],
                email=cleaned_data["admin_email"],
                phone=cleaned_data["admin_phone"],
                position="Administrador",
                business=business,
            )
            record_audit_event(
                request,
                AuditEvent.CREATE,
                "tenant_bootstrap",
                "Tenant creado con empresa, admin inicial y roles base.",
                entity_id=tenant.schema_name,
                metadata={
                    "business": business.business_name,
                    "admin_username": user.username,
                },
            )

        connection.set_schema_to_public()
        messages.success(
            request,
            "Tenant, dominio, empresa y usuario administrador creados correctamente.",
        )
        return redirect("platform_tenant_list")

    return render(
        request,
        "platform/tenant_form.html",
        {
            "form": form,
            "title": "Nuevo Tenant",
            "modules_individual": MODULES_INDIVIDUAL,
            "modules_business": MODULES_BUSINESS,
        },
    )


@login_required
@platform_required
def platform_tenant_edit(request, tenant_id):
    tenant = (
        Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        .filter(pk=tenant_id)
        .first()
    )
    if not tenant:
        messages.error(request, "Tenant no encontrado.")
        return redirect("platform_tenant_list")

    form = PlatformTenantEditForm(request.POST or None, instance=tenant)

    if request.method == "POST" and form.is_valid():
        tenant = form.save()
        domain_name = form.cleaned_data["domain"]
        primary_domain = tenant.domains.filter(is_primary=True).first()
        if primary_domain:
            primary_domain.domain = domain_name
            primary_domain.save()
        else:
            Domain.objects.create(domain=domain_name, tenant=tenant, is_primary=True)

        messages.success(request, f"Tenant {tenant.name} actualizado correctamente.")
        return redirect("platform_tenant_list")

    return render(
        request,
        "platform/tenant_form.html",
        {
            "form": form,
            "title": "Editar Tenant",
            "modules_individual": MODULES_INDIVIDUAL,
            "modules_business": MODULES_BUSINESS,
        },
    )


@login_required
@platform_required
@require_POST
def platform_tenant_delete(request, tenant_id):
    tenant = (
        Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        .filter(pk=tenant_id)
        .first()
    )
    if tenant:
        name = tenant.name
        tenant.delete()
        messages.success(request, f"Tenant {name} eliminado correctamente.")
    return redirect("platform_tenant_list")


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "Sesion cerrada correctamente.")
    return redirect("login")


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def create_employee_view(request):

    if not is_tenant_request(request):
        messages.error(
            request, "Los empleados solo se crean dentro del dominio de una empresa."
        )
        if request.user.is_staff or request.user.is_superuser:
            return redirect("platform_dashboard")
        return redirect("login")

    business = Business.objects.first()

    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    form = EmployeeCreateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        cleaned_data = form.cleaned_data
        with transaction.atomic():
            user = get_user_model().objects.create_user(
                username=cleaned_data["username"],
                password=cleaned_data["password1"],
                email=cleaned_data["email"],
                first_name=cleaned_data["first_name"],
                last_name=cleaned_data["last_name"],
            )
            user.groups.set(cleaned_data["groups"])

            Employee.objects.create(
                user=user,
                first_name=cleaned_data["first_name"],
                last_name=cleaned_data["last_name"],
                email=cleaned_data["email"],
                phone=cleaned_data["phone"],
                position=cleaned_data["position"],
                business=business,
            )
            record_audit_event(
                request,
                AuditEvent.CREATE,
                "employee",
                f"Empleado creado: {cleaned_data['first_name']} {cleaned_data['last_name']}",
                entity_id=user.pk,
                metadata={
                    "username": user.username,
                    "groups": [group.name for group in cleaned_data["groups"]],
                },
            )

        messages.success(
            request, "Empleado creado correctamente y con acceso al sistema."
        )
        return redirect("employee_list")

    return render(
        request, "employee/create_employee.html", {"form": form, "business": business}
    )


@login_required
@tenant_required
def employee_list(request):
    employees = Employee.objects.select_related("user", "business").order_by(
        "first_name", "last_name"
    )
    return render(request, "employee/employee_list.html", {"employees": employees})


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def employee_edit(request, employee_id):
    employee = (
        Employee.objects.select_related("user", "business")
        .filter(pk=employee_id)
        .first()
    )
    if employee is None:
        messages.error(request, "Empleado no encontrado.")
        return redirect("employee_list")

    form = EmployeeEditForm(request.POST or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        employee.first_name = cleaned["first_name"]
        employee.last_name = cleaned["last_name"]
        employee.email = cleaned["email"]
        employee.phone = cleaned["phone"]
        employee.position = cleaned["position"]
        employee.save()

        user = employee.user
        user.first_name = cleaned["first_name"]
        user.last_name = cleaned["last_name"]
        user.email = cleaned["email"]
        user.groups.set(cleaned["groups"])
        user.save()

        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "employee",
            f"Empleado actualizado: {employee.first_name} {employee.last_name}",
            entity_id=employee.pk,
            metadata={
                "username": user.username,
                "groups": [group.name for group in user.groups.all()],
            },
        )
        messages.success(request, "Empleado actualizado correctamente.")
        return redirect("employee_list")

    return render(
        request,
        "employee/employee_form.html",
        {"form": form, "business": employee.business, "employee": employee},
    )


@login_required
@tenant_required
def tenant_user_list(request):
    users = get_user_model().objects.prefetch_related("groups").order_by("username")
    return render(request, "tenant/users.html", {"users": users})


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def tenant_user_edit(request, user_id):
    user = (
        get_user_model().objects.filter(pk=user_id).prefetch_related("groups").first()
    )
    if user is None:
        messages.error(request, "Usuario no encontrado.")
        return redirect("tenant_user_list")

    form = TenantUserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        user.groups.set(form.cleaned_data["groups"])
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "user",
            f"Usuario actualizado: {user.username}",
            entity_id=user.pk,
            metadata={"groups": [group.name for group in user.groups.all()]},
        )
        messages.success(request, "Usuario actualizado correctamente.")
        return redirect("tenant_user_list")

    return render(request, "tenant/user_form.html", {"form": form, "user_obj": user})


@login_required
@tenant_required
def tenant_group_list(request):
    ensure_default_tenant_groups()
    groups = Group.objects.order_by("name")
    return render(request, "tenant/groups.html", {"groups": groups})


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def tenant_group_create(request):
    form = TenantGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "group",
            f"Grupo creado: {group.name}",
            entity_id=group.pk,
        )
        messages.success(request, "Grupo creado correctamente.")
        return redirect("tenant_group_list")
    return render(request, "tenant/group_form.html", {"form": form})


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def tenant_group_edit(request, group_id):
    group = Group.objects.filter(pk=group_id).first()
    if group is None:
        messages.error(request, "Grupo no encontrado.")
        return redirect("tenant_group_list")

    form = TenantGroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "group",
            f"Grupo actualizado: {group.name}",
            entity_id=group.pk,
            metadata={"permissions": [p.codename for p in group.permissions.all()]},
        )
        messages.success(request, "Grupo actualizado correctamente.")
        return redirect("tenant_group_list")

    return render(request, "tenant/group_form.html", {"form": form, "group_obj": group})


@login_required
@tenant_required
def third_party_list(request):
    third_parties = ThirdParty.objects.order_by("name")
    return render(
        request, "tenant/third_parties.html", {"third_parties": third_parties}
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
def third_party_create(request):
    form = ThirdPartyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        third_party = form.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "third_party",
            f"Tercero creado: {third_party.name}",
            entity_id=third_party.pk,
        )
        messages.success(request, "Tercero creado correctamente.")
        return redirect("third_party_list")
    return render(
        request,
        "tenant/third_party_form.html",
        {
            "form": form,
            "page_title": "Crear tercero",
            "submit_label": "Guardar tercero",
        },
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
def third_party_edit(request, third_party_id):
    third_party = ThirdParty.objects.filter(pk=third_party_id).first()
    if third_party is None:
        messages.error(request, "Tercero no encontrado.")
        return redirect("third_party_list")

    form = ThirdPartyForm(request.POST or None, instance=third_party)
    if request.method == "POST" and form.is_valid():
        third_party = form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "third_party",
            f"Tercero actualizado: {third_party.name}",
            entity_id=third_party.pk,
            metadata={"is_active": third_party.is_active},
        )
        messages.success(request, "Tercero actualizado correctamente.")
        return redirect("third_party_list")

    return render(
        request,
        "tenant/third_party_form.html",
        {
            "form": form,
            "page_title": "Editar tercero",
            "submit_label": "Guardar cambios",
            "third_party": third_party,
        },
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def third_party_toggle_active(request, third_party_id):
    third_party = ThirdParty.objects.filter(pk=third_party_id).first()
    if third_party is None:
        messages.error(request, "Tercero no encontrado.")
        return redirect("third_party_list")

    third_party.is_active = not third_party.is_active
    third_party.save()
    record_audit_event(
        request,
        AuditEvent.UPDATE,
        "third_party",
        f"Tercero {'habilitado' if third_party.is_active else 'inhabilitado'}: {third_party.name}",
        entity_id=third_party.pk,
        metadata={"is_active": third_party.is_active},
    )
    messages.success(
        request,
        f"Tercero {'habilitado' if third_party.is_active else 'inhabilitado'} correctamente.",
    )
    return redirect("third_party_list")


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def financial_entry_list(request):

    entries = FinancialEntry.objects.select_related(
        "third_party", "created_by", "business", "project", "category"
    ).all()
    # Filters
    entry_type = request.GET.get("type")
    status = request.GET.get("status")
    project_id = request.GET.get("project")
    category_id = request.GET.get("category")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    created_by = request.GET.get("created_by")
    currency = request.GET.get("currency")
    period = request.GET.get("period")
    export = request.GET.get("export")

    if period and not date_from:
        date_from, date_to = resolve_period_range(period)

    if entry_type:
        entries = entries.filter(entry_type=entry_type)
    if status:
        entries = entries.filter(status=status)
    if project_id:
        entries = entries.filter(project_id=project_id)
    if category_id:
        entries = entries.filter(category_id=category_id)
    if date_from:
        entries = entries.filter(entry_date__gte=date_from)
    if date_to:
        entries = entries.filter(entry_date__lte=date_to)
    if created_by:
        entries = entries.filter(created_by__username__icontains=created_by)
    if currency:
        entries = entries.filter(currency=currency)

    totals_by_currency = (
        entries.values("currency")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("currency")
    )

    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="financial_entries.csv"'
        csv_file = csv_writer(response)
        csv_file.writerow(
            [
                "Fecha",
                "Concepto",
                "Tipo",
                "Tercero",
                "Estado",
                "Monto",
                "Moneda",
                "Usuario",
                "Notas",
                "Proyecto",
                "Categoría",
            ]
        )
        for entry in entries.order_by("-entry_date", "-created_at"):
            csv_file.writerow(
                [
                    entry.entry_date,
                    entry.concept,
                    entry.get_entry_type_display(),
                    entry.third_party.name if entry.third_party else "-",
                    entry.get_status_display(),
                    entry.amount,
                    entry.currency,
                    entry.created_by.get_username() if entry.created_by else "-",
                    entry.notes,
                    entry.project.name if entry.project else "-",
                    entry.category.name if entry.category else "-",
                ]
            )
        return response

    page_num = request.GET.get("page", 1)
    try:
        page_size = int(request.GET.get("page_size", 25))
    except (TypeError, ValueError):
        page_size = 25
    paginator = Paginator(entries.order_by("-entry_date", "-created_at"), page_size)
    entries_page = paginator.get_page(page_num)
    expense_ids = [
        entry.pk for entry in entries_page if entry.entry_type == FinancialEntry.EXPENSE
    ]
    approval_map = {}
    for approval in ApprovalRequest.objects.filter(
        entity_type=ApprovalRequest.EXPENSE, entity_id__in=expense_ids
    ).order_by("entity_id", "-requested_at"):
        approval_map.setdefault(approval.entity_id, approval)
    for entry in entries_page:
        entry.approval_request = approval_map.get(entry.pk)

    return render(
        request,
        "tenant/financial_entries.html",
        {
            "entries": entries_page,
            "totals_by_currency": totals_by_currency,
            "entry_type_choices": FinancialEntry.ENTRY_TYPE_CHOICES,
            "status_choices": FinancialEntry.STATUS_CHOICES,
            "project_choices": Project.objects.all().order_by("name"),
            "category_choices": FinancialCategory.objects.all().order_by("name"),
            "selected_type": entry_type or "",
            "selected_status": status or "",
            "selected_project": project_id or "",
            "selected_category": category_id or "",
            "selected_currency": currency or "",
            "selected_created_by": created_by or "",
            "selected_date_from": date_from or "",
            "selected_date_to": date_to or "",
            "selected_period": period or "",
        },
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def financial_entry_create(request):

    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    form = FinancialEntryForm(
        request.POST or None, request.FILES or None, tenant_type=tenant_type
    )

    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.business = business
        entry.created_by = request.user
        entry.save()

        # Flujo normal pedido: si se crea el movimiento con estado PAID,
        # debe existir el registro correspondiente en Payment.
        if entry.status == FinancialEntry.PAID and not Payment.objects.filter(
            financial_entry=entry
        ).exists():
            Payment.objects.create(
                financial_entry=entry,
                payment_date=date.today(),
                amount=entry.amount,
                currency=entry.currency,
                concept=f"Pago auto-generado por creación de movimiento {entry.concept}",
                created_by=request.user,
            )
            record_audit_event(
                request,
                AuditEvent.CREATE,
                "payment",
                f"Pago auto-generado por movimiento PAID: {entry.concept}",
                entity_id=entry.pk,
                metadata={
                    "financial_entry_id": str(entry.pk),
                    "amount": str(entry.amount),
                    "currency": entry.currency,
                },
            )

        record_audit_event(
            request,
            AuditEvent.CREATE,
            "financial_entry",
            f"Movimiento creado: {entry.concept}",
            entity_id=entry.pk,
            metadata={
                "entry_type": entry.entry_type,
                "amount": str(entry.amount),
                "currency": entry.currency,
            },
        )
        messages.success(request, "Movimiento financiero creado correctamente.")
        return redirect("financial_entry_list")

    return render(
        request,
        "tenant/financial_entry_form.html",
        {
            "form": form,
            "business": business,
            "page_title": "Nuevo movimiento",
            "submit_label": "Guardar movimiento",
        },
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def financial_entry_edit(request, entry_id):

    entry = (
        FinancialEntry.objects.select_related("third_party", "business")
        .filter(pk=entry_id)
        .first()
    )
    if entry is None:
        messages.error(request, "Movimiento no encontrado.")
        return redirect("financial_entry_list")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    form = FinancialEntryForm(
        request.POST or None,
        request.FILES or None,
        instance=entry,
        tenant_type=tenant_type,
    )
    if request.method == "POST" and form.is_valid():
        entry = form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "financial_entry",
            f"Movimiento actualizado: {entry.concept}",
            entity_id=entry.pk,
            metadata={
                "entry_type": entry.entry_type,
                "amount": str(entry.amount),
                "currency": entry.currency,
                "status": entry.status,
            },
        )
        messages.success(request, "Movimiento financiero actualizado correctamente.")
        return redirect("financial_entry_list")

    return render(
        request,
        "tenant/financial_entry_form.html",
        {
            "form": form,
            "business": entry.business,
            "page_title": "Editar movimiento",
            "submit_label": "Guardar cambios",
            "financial_entry": entry,
        },
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def financial_entry_cancel(request, entry_id):

    entry = FinancialEntry.objects.filter(pk=entry_id).first()
    if entry is None:
        messages.error(request, "Movimiento no encontrado.")
        return redirect("financial_entry_list")

    if entry.status != FinancialEntry.CANCELLED:
        previous_status = entry.status
        entry.status = FinancialEntry.CANCELLED
        entry.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "financial_entry",
            f"Movimiento cancelado: {entry.concept}",
            entity_id=entry.pk,
            metadata={"previous_status": previous_status},
        )

        messages.success(request, "Movimiento cancelado correctamente.")
    else:
        messages.info(request, "El movimiento ya estaba cancelado.")
    return redirect("financial_entry_list")


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
def currency_rate_edit(request, rate_id):
    rate = CurrencyRate.objects.filter(pk=rate_id).first()
    if rate is None:
        messages.error(request, "Tasa no encontrada.")
        return redirect("currency_rate_list")

    form = CurrencyRateForm(request.POST or None, instance=rate)
    if request.method == "POST" and form.is_valid():
        rate = form.save(commit=False)
        if rate.source == "open.er-api.com":
            rate.source = "manual"
        rate.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "currency_rate",
            f"Tasa actualizada: {rate.currency} {rate.rate_date}",
            entity_id=rate.pk,
        )
        messages.success(request, "Tasa actualizada correctamente.")
        return redirect("currency_rate_list")

    return render(
        request,
        "tenant/currency_rate_form.html",
        {
            "form": form,
            "page_title": "Editar tasa",
            "submit_label": "Guardar cambios",
            "rate": rate,
        },
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
@require_POST
def employee_toggle_active(request, employee_id):
    employee = Employee.objects.select_related("user").filter(pk=employee_id).first()
    if employee is None:
        messages.error(request, "Empleado no encontrado.")
        return redirect("employee_list")

    user = employee.user
    user.is_active = not user.is_active
    user.save()
    record_audit_event(
        request,
        AuditEvent.UPDATE,
        "employee",
        f"Empleado {'habilitado' if user.is_active else 'inhabilitado'}: {employee.first_name} {employee.last_name}",
        entity_id=employee.pk,
        metadata={"user_is_active": user.is_active},
    )
    messages.success(
        request,
        f"Empleado {'habilitado' if user.is_active else 'inhabilitado'} correctamente.",
    )
    return redirect("employee_list")


@login_required
@tenant_required
def currency_rate_list(request):
    rates = CurrencyRate.objects.order_by("-rate_date", "currency")[:60]
    return render(request, "tenant/currency_rates.html", {"rates": rates})


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
def currency_rate_create(request):
    form = CurrencyRateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        rate = form.save(commit=False)
        if rate.source == "open.er-api.com":
            rate.source = "manual"
        rate.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "currency_rate",
            f"Tasa registrada: {rate.currency}",
            entity_id=rate.pk,
        )
        messages.success(request, "Tasa de cambio registrada correctamente.")
        return redirect("currency_rate_list")
    return render(request, "tenant/currency_rate_form.html", {"form": form})


@login_required
@tenant_required
def audit_event_list(request):
    events = AuditEvent.objects.select_related("actor").all()
    actor = request.GET.get("actor")
    action = request.GET.get("action")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if actor:
        events = events.filter(actor__username__icontains=actor)
    if action:
        events = events.filter(action=action)
    if date_from:
        events = events.filter(created_at__gte=date_from)
    if date_to:
        events = events.filter(created_at__lte=date_to)

    page_num = request.GET.get("page", 1)
    try:
        page_size = int(request.GET.get("page_size", 50))
    except (TypeError, ValueError):
        page_size = 50
    paginator = Paginator(events.order_by("-created_at"), page_size)
    events_page = paginator.get_page(page_num)

    return render(request, "tenant/audit_events.html", {"events": events_page})


def _approval_target(entity_type, entity_id):
    if entity_type == ApprovalRequest.QUOTE:
        target = Quote.objects.select_related("business").filter(pk=entity_id).first()
        if target:
            return target, target.business, f"Cotización {target.quote_number}", target.total, target.currency, f"/quotes/{target.pk}/"
    elif entity_type == ApprovalRequest.EXPENSE:
        target = FinancialEntry.objects.select_related("business").filter(
            pk=entity_id, entry_type=FinancialEntry.EXPENSE
        ).first()
        if target:
            return target, target.business, target.concept, target.amount, target.currency, "/finance/"
    return None


@login_required
@tenant_required
@module_enabled_required("approvals")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def approval_request_create(request, entity_type, entity_id):
    target_data = _approval_target(entity_type, entity_id)
    if not target_data:
        messages.error(request, "El documento no existe o no admite aprobación.")
        return redirect("approval_list")
    target, business, title, amount, currency, link = target_data
    existing = ApprovalRequest.objects.filter(
        entity_type=entity_type, entity_id=entity_id, status=ApprovalRequest.PENDING
    ).first()
    if existing:
        messages.info(request, "Este documento ya tiene una aprobación pendiente.")
        return redirect("approval_detail", approval_id=existing.pk)

    form = ApprovalRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        approval = ApprovalRequest.objects.create(
            business=business,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            amount=amount,
            currency=currency,
            reason=form.cleaned_data["reason"],
            requested_by=request.user,
        )
        notify_users(
            title=f"Aprobación pendiente: {title}",
            message=f"{request.user.get_username()} solicita aprobar {amount} {currency}.",
            link=f"/approvals/{approval.pk}/",
            level=Notification.WARNING,
            entity="approval",
            entity_id=approval.pk,
            dedupe_key=f"approval-pending-{approval.pk}",
            group_names=("Administrador de empresa",),
        )
        record_audit_event(request, AuditEvent.CREATE, "approval", f"Aprobación solicitada: {title}", approval.pk)
        messages.success(request, "Solicitud de aprobación creada.")
        return redirect("approval_detail", approval_id=approval.pk)
    return render(request, "tenant/approval_request_form.html", {"form": form, "target_title": title, "amount": amount, "currency": currency})


@login_required
@tenant_required
@module_enabled_required("approvals")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def approval_list(request):
    approvals = ApprovalRequest.objects.select_related("requested_by", "reviewed_by")
    status = request.GET.get("status")
    if status:
        approvals = approvals.filter(status=status)
    return render(request, "tenant/approval_list.html", {"approvals": approvals[:100], "status_choices": ApprovalRequest.STATUS_CHOICES, "selected_status": status or ""})


@login_required
@tenant_required
@module_enabled_required("approvals")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def approval_detail(request, approval_id):
    approval = ApprovalRequest.objects.select_related("requested_by", "reviewed_by").filter(pk=approval_id).first()
    if not approval:
        messages.error(request, "Solicitud no encontrada.")
        return redirect("approval_list")
    return render(request, "tenant/approval_detail.html", {"approval": approval, "decision_form": ApprovalDecisionForm()})


@login_required
@tenant_required
@module_enabled_required("approvals")
@tenant_group_required("Administrador de empresa")
@require_POST
def approval_decide(request, approval_id):
    form = ApprovalDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Complete correctamente la decisión.")
        return redirect("approval_detail", approval_id=approval_id)
    with transaction.atomic():
        approval = ApprovalRequest.objects.select_for_update().filter(pk=approval_id).first()
        if not approval:
            messages.error(request, "Solicitud no encontrada.")
            return redirect("approval_list")
        if approval.status != ApprovalRequest.PENDING:
            messages.info(request, "Esta solicitud ya fue decidida.")
            return redirect("approval_detail", approval_id=approval.pk)
        approval.status = form.cleaned_data["action"]
        approval.decision_notes = form.cleaned_data["decision_notes"]
        approval.reviewed_by = request.user
        approval.reviewed_at = timezone.now()
        approval.save(update_fields=["status", "decision_notes", "reviewed_by", "reviewed_at"])
        Notification.objects.create(
            recipient=approval.requested_by,
            title=f"Solicitud {approval.get_status_display().lower()}: {approval.title}",
            message=approval.decision_notes or f"Decisión registrada por {request.user.get_username()}.",
            link=f"/approvals/{approval.pk}/",
            level=Notification.SUCCESS if approval.status == ApprovalRequest.APPROVED else Notification.DANGER,
            entity="approval",
            entity_id=str(approval.pk),
            dedupe_key=f"approval-decision-{approval.pk}",
        )
        record_audit_event(request, AuditEvent.UPDATE, "approval", f"Solicitud {approval.get_status_display()}: {approval.title}", approval.pk)
    messages.success(request, f"Solicitud {approval.get_status_display().lower()}.")
    return redirect("approval_detail", approval_id=approval.pk)


@login_required
@tenant_required
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user)
    if request.GET.get("status") == "unread":
        notifications = notifications.filter(is_read=False)
    paginator = Paginator(notifications, 30)
    return render(
        request,
        "tenant/notification_list.html",
        {"notifications": paginator.get_page(request.GET.get("page", 1))},
    )


@login_required
@tenant_required
@require_POST
def notification_read_all(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    messages.success(request, "Notificaciones marcadas como leídas.")
    return redirect("notification_list")


@login_required
@tenant_required
def notification_open(request, notification_id):
    notification = Notification.objects.filter(
        pk=notification_id, recipient=request.user
    ).first()
    if not notification:
        messages.error(request, "Notificación no encontrada.")
        return redirect("notification_list")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    if notification.link.startswith("/") and not notification.link.startswith("//"):
        return redirect(notification.link)
    return redirect("notification_list")


@login_required
def create_business(request):
    return redirect_platform_managed_section(request)


@login_required
def business_list(request):
    return redirect_platform_managed_section(request)


@login_required
@tenant_required
@module_enabled_required("invoices")
def invoice_list(request):
    invoices = Invoice.objects.select_related(
        "third_party", "created_by", "project"
    ).all()
    status = request.GET.get("status")
    project_id = request.GET.get("project")
    due_from = request.GET.get("due_from")
    due_to = request.GET.get("due_to")

    if status:
        invoices = invoices.filter(status=status)
    if project_id:
        invoices = invoices.filter(project_id=project_id)
    if due_from:
        invoices = invoices.filter(due_date__gte=due_from)
    if due_to:
        invoices = invoices.filter(due_date__lte=due_to)

    page_num = request.GET.get("page", 1)
    paginator = Paginator(invoices.order_by("-issue_date"), 25)
    invoices_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/invoice_list.html",
        {
            "invoices": invoices_page,
            "status_choices": Invoice.STATUS_CHOICES,
            "project_choices": Project.objects.all().order_by("name"),
            "selected_status": status or "",
            "selected_project": project_id or "",
        },
    )


def _validated_line_items(request):
    descriptions = request.POST.getlist("item_description")
    quantities = request.POST.getlist("item_quantity")
    prices = request.POST.getlist("item_price")
    items = []
    for description, quantity, price in zip(descriptions, quantities, prices):
        description = description.strip()
        if not description and not quantity and not price:
            continue
        try:
            quantity_value = Decimal(quantity)
            price_value = Decimal(price)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Todas las líneas deben tener cantidad y precio válidos.")
        if not description:
            raise ValueError("Todas las líneas deben tener una descripción.")
        if quantity_value <= 0 or price_value <= 0:
            raise ValueError("La cantidad y el precio deben ser mayores que cero.")
        items.append((description, quantity_value, price_value))
    if not items:
        raise ValueError("Agregue al menos una línea al documento.")
    return items


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def invoice_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = InvoiceForm(request.POST, tenant_type=tenant_type)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.business = business
            invoice.created_by = request.user

            # Procesar items
            try:
                line_items = _validated_line_items(request)
                with transaction.atomic():
                    invoice.save()
                    subtotal = Decimal("0")

                    for desc, qty_dec, price_dec in line_items:
                        item_subtotal = qty_dec * price_dec
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            description=desc,
                            quantity=qty_dec,
                            unit_price=price_dec,
                            subtotal=item_subtotal,
                        )
                        subtotal += item_subtotal

                    invoice.tax_rules.set(form.cleaned_data["tax_rules"])
                    invoice.calculate_totals(subtotal)
                    invoice.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    record_audit_event(
                        request,
                        AuditEvent.CREATE,
                        "invoice",
                        f"Factura creada: {invoice.invoice_number}",
                        entity_id=invoice.pk,
                        metadata={
                            "invoice_number": invoice.invoice_number,
                            "total": str(invoice.total),
                        },
                    )
                    messages.success(request, "Factura creada correctamente.")
                    return redirect("invoice_list")
            except (InvalidOperation, ValueError) as exc:
                messages.error(request, str(exc))
            except Exception as e:
                messages.error(request, f"Error al crear factura: {str(e)}")
    else:
        form = InvoiceForm(tenant_type=tenant_type)

    return render(
        request,
        "tenant/invoice_form.html",
        {
            "form": form,
            "business": business,
            "page_title": "Nueva factura",
        },
    )


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def invoice_edit(request, invoice_id):
    invoice = Invoice.objects.select_related("business").filter(pk=invoice_id).first()
    if invoice is None:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")
    if invoice.status != Invoice.DRAFT:
        messages.warning(request, "Solo se pueden editar facturas en borrador.")
        return redirect("invoice_detail", invoice_id=invoice.pk)

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = InvoiceForm(request.POST, instance=invoice, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    invoice = form.save(commit=False)
                    # Limpiar items anteriores y crear nuevos dentro de la transacción
                    invoice.items.all().delete()
                    line_items = _validated_line_items(request)
                    
                    invoice.save()
                    subtotal = Decimal("0")

                    for desc, qty_dec, price_dec in line_items:
                        item_subtotal = qty_dec * price_dec
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            description=desc,
                            quantity=qty_dec,
                            unit_price=price_dec,
                            subtotal=item_subtotal,
                        )
                        subtotal += item_subtotal

                    invoice.tax_rules.set(form.cleaned_data["tax_rules"])
                    invoice.calculate_totals(subtotal)
                    invoice.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    record_audit_event(
                        request,
                        AuditEvent.UPDATE,
                        "invoice",
                        f"Factura actualizada: {invoice.invoice_number}",
                        entity_id=invoice.pk,
                        metadata={
                            "status": invoice.status,
                            "total": str(invoice.total),
                        },
                    )
                    messages.success(request, "Factura actualizada correctamente.")
                    return redirect("invoice_detail", invoice_id=invoice.pk)
            except (InvalidOperation, ValueError) as exc:
                messages.error(request, str(exc))
            except Exception as e:
                messages.error(request, f"Error al actualizar factura: {str(e)}")
    else:
        form = InvoiceForm(instance=invoice, tenant_type=tenant_type)

    return render(
        request,
        "tenant/invoice_form.html",
        {
            "form": form,
            "business": invoice.business,
            "page_title": "Editar factura",
            "invoice": invoice,
        },
    )


@login_required
@tenant_required
@module_enabled_required("invoices")
def invoice_detail(request, invoice_id):
    invoice = (
        Invoice.objects.select_related("business", "third_party", "created_by")
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")

    return render(request, "tenant/invoice_detail.html", {"invoice": invoice})


@login_required
@tenant_required
@module_enabled_required("invoices")
def invoice_pdf(request, invoice_id):
    """Generate PDF invoice"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
            PageBreak,
        )
        from datetime import datetime
    except ImportError:
        messages.error(
            request, "ReportLab no está instalado. Instala: pip install reportlab"
        )
        return redirect("invoice_detail", invoice_id=invoice_id)

    invoice = (
        Invoice.objects.select_related("business", "third_party")
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None:
        return redirect("invoice_list")

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # Title and invoice info
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#1f3a93"),
        spaceAfter=30,
    )

    elements.append(Paragraph(f"FACTURA {invoice.invoice_number}", title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Business and invoice details
    info_data = [
        ["EMPRESA", invoice.business.business_name],
        ["CLIENTE", invoice.third_party.name if invoice.third_party else "N/A"],
        ["FECHA EMISIÓN", invoice.issue_date.strftime("%d/%m/%Y")],
        [
            "FECHA VENCIMIENTO",
            invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else "N/A",
        ],
        ["ESTADO", invoice.get_status_display()],
    ]

    info_table = Table(info_data, colWidths=[2 * inch, 4 * inch])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(info_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Items table
    items_data = [["Descripción", "Cantidad", "Precio Unitario", "Subtotal"]]
    for item in invoice.items.all():
        items_data.append(
            [
                item.description,
                str(item.quantity),
                f"${item.unit_price:.2f}",
                f"${item.subtotal:.2f}",
            ]
        )

    items_table = Table(
        items_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f9f9f9")],
                ),
            ]
        )
    )

    elements.append(items_table)
    elements.append(Spacer(1, 0.2 * inch))

    # Totals
    totals_data = [
        ["SUBTOTAL", f"${invoice.subtotal:.2f} {invoice.currency}"],
        ["IMPUESTOS", f"${invoice.tax_amount:.2f}"],
        ["RETENCIONES", f"-${invoice.retention_amount:.2f}"],
        ["TOTAL", f"${invoice.total:.2f} {invoice.currency}"],
    ]

    totals_table = Table(totals_data, colWidths=[3.5 * inch, 2.5 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("FONTSIZE", (0, 3), (-1, 3), 12),
                ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, 3), (-1, 3), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(totals_table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'
    )
    return response


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def invoice_delete(request, invoice_id):
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")

    # B2 FIX: Removed direct invoice.delete() in favor of invoice_cancel # B2 FIX: Removed duplicated function
    messages.error(request, "La eliminación directa de facturas no está permitida. Utilice la opción de anular.")

    return redirect("invoice_list")


def _issue_invoice(invoice, created_by_user):
    """Emite una factura en borrador y crea su cuenta por cobrar una sola vez."""
    if invoice.status != Invoice.DRAFT:
        if invoice.financial_entry_id:
            return invoice.financial_entry
        raise ValueError("Solo se pueden emitir facturas en borrador.")
    if invoice.total <= 0 or not invoice.items.exists():
        raise ValueError("La factura debe tener al menos una línea y total mayor que cero.")

    financial_entry = invoice.financial_entry
    if financial_entry is None:
        financial_entry = FinancialEntry.objects.create(
            business=invoice.business,
            project=invoice.project,
            third_party=invoice.third_party,
            created_by=created_by_user,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PENDING,
            concept=f"Factura {invoice.invoice_number}",
            amount=invoice.total,
            currency=invoice.currency,
            entry_date=invoice.issue_date,
            due_date=invoice.due_date,
            notes=invoice.notes or "",
            personal=False,
        )
        invoice.financial_entry = financial_entry
    invoice.status = Invoice.ISSUED
    invoice.save(update_fields=["financial_entry", "status"])
    return financial_entry


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def invoice_issue(request, invoice_id):
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if not invoice:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")
    try:
        with transaction.atomic():
            entry = _issue_invoice(invoice, request.user)
            record_audit_event(
                request,
                AuditEvent.UPDATE,
                "invoice",
                f"Factura emitida: {invoice.invoice_number}",
                entity_id=invoice.pk,
                metadata={"financial_entry_id": entry.pk, "total": str(invoice.total)},
            )
            notify_users(
                title=f"Factura {invoice.invoice_number} emitida",
                message=f"Se creó una cuenta por cobrar por {invoice.total} {invoice.currency}.",
                link=f"/invoices/{invoice.pk}/",
                level=Notification.INFO,
                entity="invoice",
                entity_id=invoice.pk,
                dedupe_key=f"invoice-issued-{invoice.pk}",
            )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Factura {invoice.invoice_number} emitida y enviada a cartera.")
    return redirect("invoice_detail", invoice_id=invoice.pk)


def _cancel_invoice(invoice):
    if invoice.status == Invoice.CANCELLED:
        return
    if invoice.status == Invoice.PAID:
        raise ValueError("Una factura pagada no puede anularse; use una nota crédito.")
    if invoice.financial_entry_id and invoice.financial_entry.payments.exists():
        raise ValueError("La factura tiene pagos registrados; use una nota crédito.")
    invoice.status = Invoice.CANCELLED
    invoice.save(update_fields=["status"])
    if invoice.financial_entry_id:
        invoice.financial_entry.status = FinancialEntry.CANCELLED
        invoice.financial_entry.save(update_fields=["status"])


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def invoice_cancel(request, invoice_id):
    """Anula la factura y su movimiento financiero asociado sin borrar físicamente."""
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if not invoice:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")
    
    try:
        with transaction.atomic():
            _cancel_invoice(invoice)
            record_audit_event(
                request, AuditEvent.UPDATE, "invoice",
                f"Factura anulada: {invoice.invoice_number}",
                entity_id=invoice.pk
            )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("invoice_detail", invoice_id=invoice.pk)
    
    messages.success(request, f"Factura {invoice.invoice_number} anulada correctamente.")
    return redirect("invoice_detail", invoice_id=invoice.pk)


@login_required
@tenant_required
@module_enabled_required("invoices")
def quote_list(request):
    quotes = Quote.objects.select_related("project", "third_party", "created_by", "business").all()
    status = request.GET.get("status")
    project_id = request.GET.get("project")
    due_from = request.GET.get("due_from")
    due_to = request.GET.get("due_to")

    if status:
        quotes = quotes.filter(status=status)
    if project_id:
        quotes = quotes.filter(project_id=project_id)
    if due_from:
        quotes = quotes.filter(due_date__gte=due_from)
    if due_to:
        quotes = quotes.filter(due_date__lte=due_to)

    page_num = request.GET.get("page", 1)
    paginator = Paginator(quotes.order_by("-issue_date"), 25)
    quotes_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/quote_list.html",
        {
            "quotes": quotes_page,
            "status_choices": Quote.STATUS_CHOICES,
            "project_choices": Project.objects.all().order_by("name"),
            "selected_status": status or "",
            "selected_project": project_id or "",
        },
    )


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def quote_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)

    if request.method == "POST":
        form = QuoteForm(request.POST, tenant_type=tenant_type)
        if form.is_valid():
            with transaction.atomic():
                quote = form.save(commit=False)
                quote.business = business
                quote.created_by = request.user
                quote.status = Quote.DRAFT

                items_data = request.POST.getlist("item_description")
                quantities = request.POST.getlist("item_quantity")
                prices = request.POST.getlist("item_price")

                quote.save()
                subtotal = Decimal("0")

                for desc, qty, price in zip(items_data, quantities, prices):
                    if desc and qty and price:
                        qty_dec = Decimal(qty)
                        price_dec = Decimal(price)
                        item_subtotal = qty_dec * price_dec
                        QuoteItem.objects.create(
                            quote=quote,
                            description=desc,
                            quantity=qty_dec,
                            unit_price=price_dec,
                            subtotal=item_subtotal,
                        )
                        subtotal += item_subtotal

                quote.tax_rules.set(form.cleaned_data["tax_rules"])
                quote.calculate_totals(subtotal)
                quote.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                record_audit_event(
                    request,
                    AuditEvent.CREATE,
                    "quote",
                    f"Cotización creada: {quote.quote_number}",
                    entity_id=quote.pk,
                    metadata={"quote_number": quote.quote_number, "total": str(quote.total)},
                )

            messages.success(request, "Cotización creada correctamente.")
            return redirect("quote_detail", quote_id=quote.pk)

    else:
        form = QuoteForm(tenant_type=tenant_type)

    return render(
        request,
        "tenant/quote_form.html",
        {"form": form, "page_title": "Nueva cotización", "business": business},
    )


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def quote_edit(request, quote_id):
    quote = Quote.objects.select_related("business").filter(pk=quote_id).first()
    if not quote:
        messages.error(request, "Cotización no encontrada.")
        return redirect("quote_list")
    
    if quote.status not in [Quote.DRAFT]:
        messages.warning(request, "Solo se pueden editar cotizaciones en estado borrador.")
        return redirect("quote_detail", quote_id=quote.pk)

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = QuoteForm(request.POST, instance=quote, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    quote = form.save()
                    quote.items.all().delete()
                    
                    items_data = request.POST.getlist("item_description")
                    quantities = request.POST.getlist("item_quantity")
                    prices = request.POST.getlist("item_price")
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            QuoteItem.objects.create(
                                quote=quote, description=desc, quantity=qty_dec,
                                unit_price=price_dec, subtotal=item_subtotal
                            )
                            subtotal += item_subtotal

                    quote.tax_rules.set(form.cleaned_data["tax_rules"])
                    quote.calculate_totals(subtotal)
                    quote.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])
                    record_audit_event(
                        request,
                        AuditEvent.UPDATE,
                        "quote",
                        f"Cotización actualizada: {quote.quote_number}",
                        entity_id=quote.pk,
                        metadata={"total": str(quote.total)},
                    )
                    messages.success(request, "Cotización actualizada correctamente.")
                    return redirect("quote_detail", quote_id=quote.pk)
            except Exception as e:
                messages.error(request, f"Error al actualizar: {str(e)}")
    else:
        form = QuoteForm(instance=quote, tenant_type=tenant_type)

    return render(
        request,
        "tenant/quote_form.html",
        {
            "form": form,
            "page_title": "Editar cotización",
            "quote": quote,
            "business": quote.business,
        },
    )


@login_required
@tenant_required
@module_enabled_required("invoices")
def quote_detail(request, quote_id):
    quote = (
        Quote.objects.select_related("business", "project", "third_party", "created_by")
        .filter(pk=quote_id)
        .first()
    )
    if quote is None:
        messages.error(request, "Cotización no encontrada.")
        return redirect("quote_list")
    approval = ApprovalRequest.objects.filter(
        entity_type=ApprovalRequest.QUOTE, entity_id=quote.pk
    ).first()
    return render(request, "tenant/quote_detail.html", {"quote": quote, "approval": approval})


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def quote_accept(request, quote_id):
    quote = Quote.objects.filter(pk=quote_id).first()
    if quote is None:
        messages.error(request, "Cotización no encontrada.")
        return redirect("quote_list")

    if quote.status != Quote.DRAFT:
        messages.info(request, "Solo se puede aceptar una cotización en borrador.")
        return redirect("quote_detail", quote_id=quote.pk)

    if request.tenant.is_module_enabled("approvals"):
        approved = ApprovalRequest.objects.filter(
            entity_type=ApprovalRequest.QUOTE,
            entity_id=quote.pk,
            status=ApprovalRequest.APPROVED,
        ).exists()
        if not approved:
            messages.warning(request, "La cotización requiere aprobación antes de aceptarse.")
            return redirect("quote_detail", quote_id=quote.pk)

    if quote.due_date and quote.due_date < date.today():
        quote.status = Quote.EXPIRED
        quote.save(update_fields=["status"])
        messages.warning(request, "La cotización venció y no puede ser aceptada.")
        return redirect("quote_detail", quote_id=quote.pk)

    quote.status = Quote.ACCEPTED
    quote.save(update_fields=["status"])

    record_audit_event(
        request,
        AuditEvent.UPDATE,
        "quote",
        f"Cotización aceptada: {quote.quote_number}",
        entity_id=quote.pk,
        metadata={"status": quote.status},
    )
    notify_users(
        title=f"Cotización {quote.quote_number} aceptada",
        message=f"La cotización por {quote.total} {quote.currency} está lista para facturar.",
        link=f"/quotes/{quote.pk}/",
        level=Notification.SUCCESS,
        entity="quote",
        entity_id=quote.pk,
        dedupe_key=f"quote-accepted-{quote.pk}",
    )

    messages.success(request, "Cotización aceptada correctamente.")
    return redirect("quote_detail", quote_id=quote.pk)


def _convert_quote_to_invoice(quote: Quote, created_by_user):
    """
    Crea Invoice + InvoiceItems + FinancialEntry para cartera.
    Idempotencia: si quote ya tiene converted_invoice o financial_entry, reutiliza/evita duplicar.
    """
    if quote.converted_invoice_id and quote.financial_entry_id:
        return quote.converted_invoice, quote.financial_entry

    if quote.status not in (Quote.ACCEPTED, Quote.CONVERTED):
        raise ValueError("Solo se puede convertir una cotización aceptada.")

    if quote.converted_invoice_id:
        invoice = quote.converted_invoice
    else:
        invoice = Invoice.objects.create(
            business=quote.business,
            project=quote.project,
            third_party=quote.third_party,
            status=Invoice.ISSUED,
            issue_date=quote.issue_date,
            due_date=quote.due_date,
            description=quote.description,
            notes=quote.notes,
            currency=quote.currency,
            created_by=created_by_user,
        )
        invoice.tax_rules.set(quote.tax_rules.all())

        subtotal = Decimal("0")
        for qitem in quote.items.all():
            item_subtotal = qitem.quantity * qitem.unit_price
            InvoiceItem.objects.create(
                invoice=invoice,
                description=qitem.description,
                quantity=qitem.quantity,
                unit_price=qitem.unit_price,
                subtotal=item_subtotal,
            )
            subtotal += item_subtotal

        invoice.calculate_totals(subtotal)
        invoice.save(
            update_fields=["subtotal", "tax_amount", "retention_amount", "total"]
        )

    financial_entry = quote.financial_entry or invoice.financial_entry
    if financial_entry is None:
        financial_entry = FinancialEntry.objects.create(
            business=quote.business,
            project=quote.project,
            category=None,
            third_party=quote.third_party,
            created_by=created_by_user,
            entry_type=FinancialEntry.ACCOUNT_RECEIVABLE,
            status=FinancialEntry.PENDING,
            concept=f"Cotización {quote.quote_number} → Factura {invoice.invoice_number}",
            amount=invoice.total,
            currency=invoice.currency,
            entry_date=quote.issue_date,
            due_date=invoice.due_date,
            notes=quote.notes or "",
            personal=False,
        )

    if invoice.financial_entry_id != financial_entry.pk:
        invoice.financial_entry = financial_entry
        invoice.save(update_fields=["financial_entry"])

    quote.converted_invoice = invoice
    quote.financial_entry = financial_entry
    quote.status = Quote.CONVERTED
    quote.save(update_fields=["converted_invoice", "financial_entry", "status"])

    return invoice, financial_entry


@login_required
@tenant_required
@module_enabled_required("invoices")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def quote_convert_to_invoice(request, quote_id):
    quote = Quote.objects.select_related("business", "project", "third_party").filter(pk=quote_id).first()
    if quote is None:
        messages.error(request, "Cotización no encontrada.")
        return redirect("quote_list")

    try:
        with transaction.atomic():
            invoice, fin_entry = _convert_quote_to_invoice(quote, request.user)
    except ValueError as e:
        messages.info(request, str(e))
        return redirect("quote_detail", quote_id=quote.pk)
    except Exception as e:
        messages.error(request, f"Error al convertir: {str(e)}")
        return redirect("quote_detail", quote_id=quote.pk)

    messages.success(request, "Cotización convertida a factura correctamente.")
    return redirect("invoice_detail", invoice_id=invoice.pk)


@login_required
@tenant_required
@module_enabled_required("credit_notes")
def credit_note_list(request):
    credit_notes = CreditNote.objects.select_related(
        "invoice", "third_party", "created_by", "business"
    ).all()
    status = request.GET.get("status")
    invoice_id = request.GET.get("invoice")
    issue_from = request.GET.get("issue_from")
    issue_to = request.GET.get("issue_to")

    if status:
        credit_notes = credit_notes.filter(status=status)
    if invoice_id:
        credit_notes = credit_notes.filter(invoice_id=invoice_id)
    if issue_from:
        credit_notes = credit_notes.filter(issue_date__gte=issue_from)
    if issue_to:
        credit_notes = credit_notes.filter(issue_date__lte=issue_to)

    page_num = request.GET.get("page", 1)
    paginator = Paginator(credit_notes.order_by("-issue_date"), 25)
    credit_notes_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/credit_note_list.html",
        {
            "credit_notes": credit_notes_page,
            "status_choices": CreditNote.STATUS_CHOICES,
            "invoice_choices": Invoice.objects.all().order_by("-issue_date"),
            "selected_status": status or "",
            "selected_invoice": invoice_id or "",
        },
    )


@login_required
@tenant_required
@module_enabled_required("credit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def credit_note_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = CreditNoteForm(request.POST, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    credit_note = form.save(commit=False)
                    credit_note.business = business
                    credit_note.created_by = request.user
                    credit_note.status = CreditNote.ISSUED # Credit notes are typically issued directly

                    items_data = request.POST.getlist("item_description")
                    quantities = request.POST.getlist("item_quantity")
                    prices = request.POST.getlist("item_price")

                    credit_note.save() # Save to generate number
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            CreditNoteItem.objects.create(
                                credit_note=credit_note,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    credit_note.tax_rules.set(form.cleaned_data["tax_rules"])
                    credit_note.calculate_totals(subtotal)
                    credit_note.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    # Create FinancialEntry for the credit note
                    financial_entry = FinancialEntry.objects.create(
                        business=business,
                        third_party=credit_note.third_party,
                        created_by=request.user,
                        entry_type=FinancialEntry.ACCOUNT_PAYABLE, # Credit note reduces AR or increases AP
                        status=FinancialEntry.PENDING,
                        concept=f"Nota de Crédito {credit_note.credit_note_number} (Factura {credit_note.invoice.invoice_number if credit_note.invoice else 'N/A'})",
                        amount=credit_note.total,
                        currency=credit_note.currency,
                        entry_date=credit_note.issue_date,
                        due_date=credit_note.issue_date, # Due date can be same as issue date for immediate effect
                        notes=credit_note.notes or "",
                        personal=False,
                    )
                    credit_note.financial_entry = financial_entry
                    credit_note.save(update_fields=["financial_entry"])

                    record_audit_event(
                        request,
                        AuditEvent.CREATE,
                        "credit_note",
                        f"Nota de Crédito creada: {credit_note.credit_note_number}",
                        entity_id=credit_note.pk,
                        metadata={
                            "credit_note_number": credit_note.credit_note_number,
                            "total": str(credit_note.total),
                        },
                    )
                    messages.success(request, "Nota de Crédito creada correctamente.")
                    return redirect("credit_note_detail", credit_note_id=credit_note.pk)
            except InvalidOperation:
                messages.error(request, "Error al crear nota de crédito: cantidad o precio inválido.")
            except Exception as e:
                messages.error(request, f"Error al crear nota de crédito: {str(e)}")
    else:
        form = CreditNoteForm(tenant_type=tenant_type)

    return render(
        request,
        "tenant/credit_note_form.html",
        {
            "form": form,
            "business": business,
            "page_title": "Nueva Nota de Crédito",
        },
    )


@login_required
@tenant_required
@module_enabled_required("credit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def credit_note_edit(request, credit_note_id):
    credit_note = CreditNote.objects.select_related("business", "financial_entry").filter(pk=credit_note_id).first()
    if not credit_note:
        messages.error(request, "Nota de Crédito no encontrada.")
        return redirect("credit_note_list")
    
    if credit_note.status == CreditNote.CANCELLED:
        messages.warning(request, "No se puede editar una nota de crédito anulada.")
        return redirect("credit_note_detail", credit_note_id=credit_note.pk)

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = CreditNoteForm(request.POST, instance=credit_note, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    credit_note = form.save(commit=False)
                    credit_note.items.all().delete()
                    
                    items_data = request.POST.getlist("item_description")
                    quantities = request.POST.getlist("item_quantity")
                    prices = request.POST.getlist("item_price")
                    
                    credit_note.save()
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            CreditNoteItem.objects.create(
                                credit_note=credit_note,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    credit_note.tax_rules.set(form.cleaned_data["tax_rules"])
                    credit_note.calculate_totals(subtotal)
                    credit_note.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    if credit_note.financial_entry:
                        fe = credit_note.financial_entry
                        fe.third_party = credit_note.third_party
                        fe.concept = f"Nota de Crédito {credit_note.credit_note_number} (Factura {credit_note.invoice.invoice_number if credit_note.invoice else 'N/A'})"
                        fe.amount = credit_note.total
                        fe.currency = credit_note.currency
                        fe.entry_date = credit_note.issue_date
                        fe.due_date = credit_note.issue_date
                        fe.notes = credit_note.notes or ""
                        fe.save()

                    record_audit_event(
                        request,
                        AuditEvent.UPDATE,
                        "credit_note",
                        f"Nota de Crédito actualizada: {credit_note.credit_note_number}",
                        entity_id=credit_note.pk,
                    )
                    messages.success(request, "Nota de Crédito actualizada correctamente.")
                    return redirect("credit_note_detail", credit_note_id=credit_note.pk)
            except Exception as e:
                messages.error(request, f"Error al actualizar: {str(e)}")
    else:
        form = CreditNoteForm(instance=credit_note, tenant_type=tenant_type)

    return render(request, "tenant/credit_note_form.html", {
        "form": form,
        "credit_note": credit_note,
        "business": credit_note.business,
        "page_title": "Editar Nota de Crédito"
    })


@login_required
@tenant_required
@module_enabled_required("credit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def credit_note_cancel(request, credit_note_id):
    credit_note = CreditNote.objects.filter(pk=credit_note_id).first()
    if not credit_note:
        messages.error(request, "Nota de Crédito no encontrada.")
        return redirect("credit_note_list")
    
    with transaction.atomic():
        credit_note.status = CreditNote.CANCELLED
        credit_note.save(update_fields=["status"])
        
        if credit_note.financial_entry:
            credit_note.financial_entry.status = FinancialEntry.CANCELLED
            credit_note.financial_entry.save(update_fields=["status"])
            
        record_audit_event(
            request, AuditEvent.UPDATE, "credit_note",
            f"Nota de Crédito anulada: {credit_note.credit_note_number}",
            entity_id=credit_note.pk
        )
    
    messages.success(request, f"Nota de Crédito {credit_note.credit_note_number} anulada correctamente.")
    return redirect("credit_note_detail", credit_note_id=credit_note.pk)


@login_required
@tenant_required
@module_enabled_required("credit_notes")
def credit_note_detail(request, credit_note_id):
    credit_note = (
        CreditNote.objects.select_related("business", "invoice", "third_party", "created_by")
        .filter(pk=credit_note_id)
        .first()
    )
    if credit_note is None:
        messages.error(request, "Nota de Crédito no encontrada.")
        return redirect("credit_note_list")

    return render(request, "tenant/credit_note_detail.html", {"credit_note": credit_note})


@login_required
@tenant_required
@module_enabled_required("debit_notes")
def debit_note_list(request):
    debit_notes = DebitNote.objects.select_related(
        "invoice", "third_party", "created_by", "business"
    ).all()
    status = request.GET.get("status")
    invoice_id = request.GET.get("invoice")
    issue_from = request.GET.get("issue_from")
    issue_to = request.GET.get("issue_to")

    if status:
        debit_notes = debit_notes.filter(status=status)
    if invoice_id:
        debit_notes = debit_notes.filter(invoice_id=invoice_id)
    if issue_from:
        debit_notes = debit_notes.filter(issue_date__gte=issue_from)
    if issue_to:
        debit_notes = debit_notes.filter(issue_date__lte=issue_to)

    page_num = request.GET.get("page", 1)
    paginator = Paginator(debit_notes.order_by("-issue_date"), 25)
    debit_notes_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/debit_note_list.html",
        {
            "debit_notes": debit_notes_page,
            "status_choices": DebitNote.STATUS_CHOICES,
            "invoice_choices": Invoice.objects.all().order_by("-issue_date"),
            "selected_status": status or "",
            "selected_invoice": invoice_id or "",
        },
    )


@login_required
@tenant_required
@module_enabled_required("debit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def debit_note_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = DebitNoteForm(request.POST, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    debit_note = form.save(commit=False)
                    debit_note.business = business
                    debit_note.created_by = request.user
                    debit_note.status = DebitNote.ISSUED # Debit notes are typically issued directly

                    items_data = request.POST.getlist("item_description")
                    quantities = request.POST.getlist("item_quantity")
                    prices = request.POST.getlist("item_price")

                    debit_note.save() # Save to generate number
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            DebitNoteItem.objects.create(
                                debit_note=debit_note,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    debit_note.tax_rules.set(form.cleaned_data["tax_rules"])
                    debit_note.calculate_totals(subtotal)
                    debit_note.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    # Create FinancialEntry for the debit note
                    financial_entry = FinancialEntry.objects.create(
                        business=business,
                        third_party=debit_note.third_party,
                        created_by=request.user,
                        entry_type=FinancialEntry.ACCOUNT_RECEIVABLE, # Debit note increases AR or reduces AP
                        status=FinancialEntry.PENDING,
                        concept=f"Nota de Débito {debit_note.debit_note_number} (Factura {debit_note.invoice.invoice_number if debit_note.invoice else 'N/A'})",
                        amount=debit_note.total,
                        currency=debit_note.currency,
                        entry_date=debit_note.issue_date,
                        due_date=debit_note.issue_date, # Due date can be same as issue date for immediate effect
                        notes=debit_note.notes or "",
                        personal=False,
                    )
                    debit_note.financial_entry = financial_entry
                    debit_note.save(update_fields=["financial_entry"])

                    record_audit_event(
                        request,
                        AuditEvent.CREATE,
                        "debit_note",
                        f"Nota de Débito creada: {debit_note.debit_note_number}",
                        entity_id=debit_note.pk,
                        metadata={
                            "debit_note_number": debit_note.debit_note_number,
                            "total": str(debit_note.total),
                        },
                    )
                    messages.success(request, "Nota de Débito creada correctamente.")
                    return redirect("debit_note_detail", debit_note_id=debit_note.pk)
            except InvalidOperation:
                messages.error(request, "Error al crear nota de débito: cantidad o precio inválido.")
            except Exception as e:
                messages.error(request, f"Error al crear nota de débito: {str(e)}")
    else:
        form = DebitNoteForm(tenant_type=tenant_type)

    return render(
        request,
        "tenant/debit_note_form.html",
        {
            "form": form,
            "business": business,
            "page_title": "Nueva Nota de Débito",
        },
    )


@login_required
@tenant_required
@module_enabled_required("debit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def debit_note_edit(request, debit_note_id):
    debit_note = DebitNote.objects.select_related("business", "financial_entry").filter(pk=debit_note_id).first()
    if not debit_note:
        messages.error(request, "Nota de Débito no encontrada.")
        return redirect("debit_note_list")
    
    if debit_note.status == DebitNote.CANCELLED:
        messages.warning(request, "No se puede editar una nota de débito anulada.")
        return redirect("debit_note_detail", debit_note_id=debit_note.pk)

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = DebitNoteForm(request.POST, instance=debit_note, tenant_type=tenant_type)
        if form.is_valid():
            try:
                with transaction.atomic():
                    debit_note = form.save(commit=False)
                    debit_note.items.all().delete()
                    
                    items_data = request.POST.getlist("item_description")
                    quantities = request.POST.getlist("item_quantity")
                    prices = request.POST.getlist("item_price")
                    
                    debit_note.save()
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            DebitNoteItem.objects.create(
                                debit_note=debit_note,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    debit_note.tax_rules.set(form.cleaned_data["tax_rules"])
                    debit_note.calculate_totals(subtotal)
                    debit_note.save(update_fields=["subtotal", "tax_amount", "retention_amount", "total"])

                    if debit_note.financial_entry:
                        fe = debit_note.financial_entry
                        fe.third_party = debit_note.third_party
                        fe.concept = f"Nota de Débito {debit_note.debit_note_number} (Factura {debit_note.invoice.invoice_number if debit_note.invoice else 'N/A'})"
                        fe.amount = debit_note.total
                        fe.currency = debit_note.currency
                        fe.entry_date = debit_note.issue_date
                        fe.due_date = debit_note.issue_date
                        fe.notes = debit_note.notes or ""
                        fe.save()

                    record_audit_event(
                        request,
                        AuditEvent.UPDATE,
                        "debit_note",
                        f"Nota de Débito actualizada: {debit_note.debit_note_number}",
                        entity_id=debit_note.pk,
                    )
                    messages.success(request, "Nota de Débito actualizada correctamente.")
                    return redirect("debit_note_detail", debit_note_id=debit_note.pk)
            except Exception as e:
                messages.error(request, f"Error al actualizar: {str(e)}")
    else:
        form = DebitNoteForm(instance=debit_note, tenant_type=tenant_type)

    return render(request, "tenant/debit_note_form.html", {
        "form": form,
        "debit_note": debit_note,
        "business": debit_note.business,
        "page_title": "Editar Nota de Débito"
    })


@login_required
@tenant_required
@module_enabled_required("debit_notes")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def debit_note_cancel(request, debit_note_id):
    debit_note = DebitNote.objects.filter(pk=debit_note_id).first()
    if not debit_note:
        messages.error(request, "Nota de Débito no encontrada.")
        return redirect("debit_note_list")
    
    with transaction.atomic():
        debit_note.status = DebitNote.CANCELLED
        debit_note.save(update_fields=["status"])
        
        if debit_note.financial_entry:
            debit_note.financial_entry.status = FinancialEntry.CANCELLED
            debit_note.financial_entry.save(update_fields=["status"])
            
        record_audit_event(
            request, AuditEvent.UPDATE, "debit_note",
            f"Nota de Débito anulada: {debit_note.debit_note_number}",
            entity_id=debit_note.pk
        )
    
    messages.success(request, f"Nota de Débito {debit_note.debit_note_number} anulada correctamente.")
    return redirect("debit_note_detail", debit_note_id=debit_note.pk)


@login_required
@tenant_required
@module_enabled_required("debit_notes")
def debit_note_detail(request, debit_note_id):
    debit_note = (
        DebitNote.objects.select_related("business", "invoice", "third_party", "created_by")
        .filter(pk=debit_note_id)
        .first()
    )
    if debit_note is None:
        messages.error(request, "Nota de Débito no encontrada.")
        return redirect("debit_note_list")

    return render(request, "tenant/debit_note_detail.html", {"debit_note": debit_note})


def _aging_bucket(days_overdue):
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "days_1_30"
    if days_overdue <= 60:
        return "days_31_60"
    if days_overdue <= 90:
        return "days_61_90"
    return "days_90_plus"


def _portfolio_risk(overdue_total, total, oldest_days):
    if total <= 0:
        return "low", "Bajo"
    overdue_ratio = overdue_total / total
    if oldest_days > 90 or overdue_ratio >= Decimal("0.50"):
        return "high", "Alto"
    if oldest_days > 30 or overdue_ratio > 0:
        return "medium", "Medio"
    return "low", "Bajo"


@login_required
@tenant_required
@module_enabled_required("cartera")
def cartera_dashboard(request):
    """
    Dashboard explícito de cartera (Accounts Receivable / Payable).

    - Alertas de vencimiento (overdue)
    - Evolución de saldo (remaining) por tercero usando Payment + Invoice/FinancialEntry
    - Panel por ThirdParty: saldo, overdue, próximos vencimientos y pagos recientes
    """
    today = date.today()

    type_filter = request.GET.get("type", "receivable")  # receivable | payable
    third_party_filter = request.GET.get("third_party", "")  # id o vacío
    project_filter = request.GET.get("project", "")
    due_range_days = request.GET.get("due_range_days", "30")
    overdue_only = request.GET.get("overdue_only", "") == "1"

    try:
        due_range_days_int = int(due_range_days)
        if due_range_days_int < 1:
            due_range_days_int = 30
    except Exception:
        due_range_days_int = 30

    entry_type = (
        FinancialEntry.ACCOUNT_RECEIVABLE
        if type_filter == "receivable"
        else FinancialEntry.ACCOUNT_PAYABLE
    )

    third_parties = ThirdParty.objects.filter(is_active=True).order_by("name")
    projects = Project.objects.order_by("name")

    # Base: sólo entradas de cartera con due_date definido y pendiente
    entries_qs = (
        FinancialEntry.objects.select_related("third_party", "project", "business")
        .filter(
            entry_type=entry_type,
            status__in=[FinancialEntry.PENDING, FinancialEntry.PARTIAL],
            due_date__isnull=False,
        )
        .exclude(due_date=None)
    )

    if third_party_filter:
        entries_qs = entries_qs.filter(third_party_id=third_party_filter)
    if project_filter:
        entries_qs = entries_qs.filter(project_id=project_filter)

    due_from = today
    due_to = today + timedelta(days=due_range_days_int)

    # Pagos del tenant (calculamos remaining por entry convirtiendo a moneda del entry)
    payments_by_entry = {}
    payments_qs = (
        Payment.objects.select_related("financial_entry", "created_by")
        .filter(financial_entry__in=entries_qs)
        .order_by("payment_date", "-created_at")
    )
    for p in payments_qs:
        payments_by_entry.setdefault(p.financial_entry_id, []).append(p)

    # Helper para cálculo remaining
    def compute_remaining(fin_entry: FinancialEntry):
        paid_sum_in_entry_currency = Decimal("0")
        for p in payments_by_entry.get(fin_entry.id, []):
            try:
                paid_sum_in_entry_currency += _convert_amount(
                    p.amount,
                    p.currency,
                    fin_entry.currency,
                    p.payment_date,
                )
            except Exception:
                # Si falla conversión, sumamos sin convertir como fallback
                paid_sum_in_entry_currency += p.amount
        remaining = fin_entry.amount - paid_sum_in_entry_currency
        return remaining

    # Construimos lista por entry con flags
    entry_rows = []
    overdue_total = Decimal("0")
    remaining_total = Decimal("0")
    overdue_count = 0
    next_due_total = Decimal("0")
    next_due_count = 0
    aging_totals = {
        "current": Decimal("0"),
        "days_1_30": Decimal("0"),
        "days_31_60": Decimal("0"),
        "days_61_90": Decimal("0"),
        "days_90_plus": Decimal("0"),
    }
    currency_totals = {}
    currency_aging = {}
    currency_overdue = {}
    currency_next_due = {}

    for e in entries_qs.select_related("third_party", "project"):
        remaining = compute_remaining(e)
        if remaining <= 0:
            continue

        is_overdue = bool(e.due_date and e.due_date < today)
        is_next_due = bool(
            e.due_date and due_from <= e.due_date <= due_to
        )  # incluye hoy

        days_overdue = max((today - e.due_date).days, 0)
        bucket = _aging_bucket(days_overdue)
        try:
            invoice = e.invoice
        except ObjectDoesNotExist:
            invoice = None
        row = {
            "entry_id": e.id,
            "concept": e.concept,
            "third_party": e.third_party,
            "third_party_id": e.third_party_id,
            "project_name": e.project.name if e.project else None,
            "project_id": e.project_id,
            "invoice_id": invoice.pk if invoice else None,
            "invoice_number": invoice.invoice_number if invoice else None,
            "due_date": e.due_date,
            "currency": e.currency,
            "remaining": remaining,
            "is_overdue": is_overdue,
            "is_next_due": is_next_due,
            "days_overdue": days_overdue,
            "aging_bucket": bucket,
        }
        entry_rows.append(row)

        remaining_total += remaining
        aging_totals[bucket] += remaining
        currency_totals[e.currency] = currency_totals.get(e.currency, Decimal("0")) + remaining
        currency_aging.setdefault(
            e.currency,
            {key: Decimal("0") for key in aging_totals},
        )[bucket] += remaining
        if is_overdue:
            overdue_total += remaining
            overdue_count += 1
            currency_overdue[e.currency] = currency_overdue.get(
                e.currency, Decimal("0")
            ) + remaining
        if is_next_due:
            next_due_total += remaining
            next_due_count += 1
            currency_next_due[e.currency] = currency_next_due.get(
                e.currency, Decimal("0")
            ) + remaining

    if overdue_only:
        entry_rows = [r for r in entry_rows if r["is_overdue"]]
        # Recalcular totales según el subconjunto
        overdue_total = Decimal("0")
        remaining_total = Decimal("0")
        overdue_count = 0
        next_due_total = Decimal("0")
        next_due_count = 0
        for r in entry_rows:
            remaining_total += r["remaining"]
            if r["is_overdue"]:
                overdue_total += r["remaining"]
                overdue_count += 1
            if r["is_next_due"]:
                next_due_total += r["remaining"]
                next_due_count += 1
        aging_totals = {key: Decimal("0") for key in aging_totals}
        currency_totals = {}
        currency_aging = {}
        currency_overdue = {}
        currency_next_due = {}
        for r in entry_rows:
            aging_totals[r["aging_bucket"]] += r["remaining"]
            currency_totals[r["currency"]] = currency_totals.get(
                r["currency"], Decimal("0")
            ) + r["remaining"]
            currency_aging.setdefault(
                r["currency"], {key: Decimal("0") for key in aging_totals}
            )[r["aging_bucket"]] += r["remaining"]
            if r["is_overdue"]:
                currency_overdue[r["currency"]] = currency_overdue.get(
                    r["currency"], Decimal("0")
                ) + r["remaining"]
            if r["is_next_due"]:
                currency_next_due[r["currency"]] = currency_next_due.get(
                    r["currency"], Decimal("0")
                ) + r["remaining"]

    # Panel por tercero
    # Filtramos terceros sólo los que tengan entries relevantes
    relevant_third_party_ids = sorted({r["third_party_id"] for r in entry_rows if r["third_party_id"]})
    third_party_map = {tp.id: tp for tp in third_parties if tp.id in relevant_third_party_ids}

    # Recent payments por tercero (top 5)
    recent_payments_by_tp = {}
    if relevant_third_party_ids:
        payments_recent = (
            Payment.objects.select_related("financial_entry", "financial_entry__third_party")
            .filter(financial_entry__entry_type=entry_type)
            .filter(financial_entry__third_party_id__in=relevant_third_party_ids)
            .order_by("-payment_date", "-created_at")[:200]
        )
        for p in payments_recent:
            tp_id = p.financial_entry.third_party_id if p.financial_entry else None
            if not tp_id:
                continue
            recent_payments_by_tp.setdefault(tp_id, []).append(p)

    # Próximos vencimientos por tercero: construimos desde entry_rows
    next_due_entries_by_tp = {}
    for r in entry_rows:
        tp_id = r["third_party_id"]
        if not tp_id:
            continue
        if r["is_overdue"] or r["is_next_due"]:
            # mostramos próximos: si está en próxima ventana o overdue
            next_due_entries_by_tp.setdefault(tp_id, []).append(r)

    # Ordenamos listas por due_date
    for tp_id, lst in next_due_entries_by_tp.items():
        lst.sort(key=lambda x: (x["is_overdue"] is False, x["due_date"]))
        next_due_entries_by_tp[tp_id] = lst

    # Agregaciones y armado de filas
    remaining_total_by_tp = {}
    overdue_total_by_tp = {}
    next_due_total_by_tp = {}
    overdue_count_by_tp = {}
    next_due_count_by_tp = {}
    oldest_days_by_tp = {}

    for r in entry_rows:
        tp_id = r["third_party_id"]
        if not tp_id:
            continue
        remaining_total_by_tp[tp_id] = remaining_total_by_tp.get(tp_id, Decimal("0")) + r["remaining"]
        if r["is_overdue"]:
            overdue_total_by_tp[tp_id] = overdue_total_by_tp.get(tp_id, Decimal("0")) + r["remaining"]
            overdue_count_by_tp[tp_id] = overdue_count_by_tp.get(tp_id, 0) + 1
            oldest_days_by_tp[tp_id] = max(
                oldest_days_by_tp.get(tp_id, 0), r["days_overdue"]
            )
        if r["is_next_due"]:
            next_due_total_by_tp[tp_id] = next_due_total_by_tp.get(tp_id, Decimal("0")) + r["remaining"]
            next_due_count_by_tp[tp_id] = next_due_count_by_tp.get(tp_id, 0) + 1

    third_party_rows = []
    for tp_id in relevant_third_party_ids:
        tp = third_party_map.get(tp_id)
        if not tp:
            continue
        tp_recent_payments = recent_payments_by_tp.get(tp_id, [])
        tp_next_due_entries = next_due_entries_by_tp.get(tp_id, [])

        tp_total = remaining_total_by_tp.get(tp_id, Decimal("0"))
        tp_overdue = overdue_total_by_tp.get(tp_id, Decimal("0"))
        risk_key, risk_label = _portfolio_risk(
            tp_overdue, tp_total, oldest_days_by_tp.get(tp_id, 0)
        )
        third_party_rows.append(
            {
                "third_party": tp,
                "remaining_total": tp_total,
                "overdue_total": tp_overdue,
                "next_due_total": next_due_total_by_tp.get(tp_id, Decimal("0")),
                "overdue_count": overdue_count_by_tp.get(tp_id, 0),
                "next_due_count": next_due_count_by_tp.get(tp_id, 0),
                "risk_key": risk_key,
                "risk_label": risk_label,
                "oldest_days": oldest_days_by_tp.get(tp_id, 0),
                "next_due_entries": [
                    {
                        "due_date": x["due_date"],
                        "concept": x["concept"],
                        "project_name": x["project_name"],
                        "is_overdue": x["is_overdue"],
                    }
                    for x in tp_next_due_entries
                ],
                "recent_payments": [
                    {
                        "payment_date": p.payment_date,
                        "amount": p.amount,
                        "currency": p.currency,
                    }
                    for p in tp_recent_payments
                ],
            }
        )

    # Etiqueta moneda (MVP: como hay múltiples monedas, mostramos moneda de FinancialEntry en cards global como first row)
    currency_label = ""
    if entry_rows:
        currency_label = entry_rows[0]["currency"]

    context = {
        "type_filter": type_filter,
        "third_parties": third_parties,
        "third_party_filter": third_party_filter,
        "projects": projects,
        "project_filter": project_filter,
        "due_range_days": due_range_days_int,
        "overdue_only": overdue_only,
        "totals": {
            "remaining_total": remaining_total,
            "entry_count": len(entry_rows),
            "overdue_total": overdue_total,
            "overdue_count": overdue_count,
            "next_due_total": next_due_total,
            "next_due_count": next_due_count,
        },
        "currency_label": currency_label,
        "recent_payments_count": sum(
            len(
                recent_payments_by_tp.get(row["third_party"].id, [])
                if row.get("third_party") else []
            )
            for row in third_party_rows
        ),
        "third_party_rows": third_party_rows,
        "entry_rows": sorted(entry_rows, key=lambda row: row["due_date"]),
        "aging_totals": aging_totals,
        "currency_totals": sorted(currency_totals.items()),
        "currency_aging": [
            {"currency": currency, **buckets}
            for currency, buckets in sorted(currency_aging.items())
        ],
        "currency_summary": [
            {
                "currency": currency,
                "total": amount,
                "overdue": currency_overdue.get(currency, Decimal("0")),
                "next_due": currency_next_due.get(currency, Decimal("0")),
            }
            for currency, amount in sorted(currency_totals.items())
        ],
    }
    return render(request, "tenant/cartera_dashboard.html", context)


@login_required
@tenant_required
@module_enabled_required("cartera")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def cartera_aging_excel_export(request):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Border, Side, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(
            request, "La librería 'openpyxl' no está instalada en el servidor. Contacte a soporte."
        )
        return redirect("cartera_dashboard")

    today = date.today()
    type_filter = request.GET.get("type", "receivable")  # receivable | payable
    third_party_filter = request.GET.get("third_party", "")
    project_filter = request.GET.get("project", "")
    entry_type = FinancialEntry.ACCOUNT_RECEIVABLE if type_filter == "receivable" else FinancialEntry.ACCOUNT_PAYABLE

    entries_qs = (
        FinancialEntry.objects.select_related("third_party", "project")
        .filter(
            entry_type=entry_type,
            status__in=[FinancialEntry.PENDING, FinancialEntry.PARTIAL],
            due_date__isnull=False,
        )
        .exclude(due_date=None)
    )
    if third_party_filter:
        entries_qs = entries_qs.filter(third_party_id=third_party_filter)
    if project_filter:
        entries_qs = entries_qs.filter(project_id=project_filter)

    payments_by_entry = {}
    payments_qs = Payment.objects.filter(financial_entry__in=entries_qs).order_by("payment_date", "-created_at")
    for p in payments_qs:
        payments_by_entry.setdefault(p.financial_entry_id, []).append(p)

    def compute_remaining(fin_entry: FinancialEntry):
        paid_sum_in_entry_currency = Decimal("0")
        for p in payments_by_entry.get(fin_entry.id, []):
            try:
                paid_sum_in_entry_currency += _convert_amount(
                    p.amount,
                    p.currency,
                    fin_entry.currency,
                    p.payment_date,
                )
            except ValueError:
                # Si la conversión de moneda falla, se ignora este pago para el cálculo del restante.
                # Esto evita un error crítico en el reporte, pero puede indicar datos faltantes.
                pass
            except Exception:
                # Captura otros errores potenciales, ignora el pago para el cálculo del restante.
                pass
        remaining = fin_entry.amount - paid_sum_in_entry_currency
        return remaining

    # Agrega datos por (third_party_id, currency) y rango de vencimiento
    third_party_aging_data = {}  # {(third_party_id, currency): {'name': '...', 'total_outstanding': Decimal, 'current': Decimal, 'bucket_30': Decimal, ...}}

    for entry in entries_qs:
        try:
            remaining = compute_remaining(entry)
        except ValueError as e:
            # Si hay un error de conversión de moneda para la entrada principal, se salta esta entrada.
            print(f"Skipping financial entry {entry.id} due to currency conversion error: {e}")
            continue

        if remaining <= 0:
            continue

        tp_id = entry.third_party_id
        currency = entry.currency
        key = (tp_id, currency)

        if key not in third_party_aging_data:
            third_party_aging_data[key] = {
                'name': entry.third_party.name if entry.third_party else 'N/A',
                'total_outstanding': Decimal('0.00'),
                'current': Decimal('0.00'),
                'bucket_30': Decimal('0.00'),
                'bucket_60': Decimal('0.00'),
                'bucket_90': Decimal('0.00'),
                'bucket_plus_90': Decimal('0.00'),
                'currency': currency
            }
        
        third_party_aging_data[key]['total_outstanding'] += remaining

        if entry.due_date:
            days_overdue = (today - entry.due_date).days
            if days_overdue <= 0:  # No vencido o vence hoy
                third_party_aging_data[key]['current'] += remaining
            elif days_overdue <= 30:
                third_party_aging_data[key]['bucket_30'] += remaining
            elif days_overdue <= 60:
                third_party_aging_data[key]['bucket_60'] += remaining
            elif days_overdue <= 90:
                third_party_aging_data[key]['bucket_90'] += remaining
            else:  # Más de 90 días vencido
                third_party_aging_data[key]['bucket_plus_90'] += remaining
        else:
            # Si no hay fecha de vencimiento, se considera al día
            third_party_aging_data[key]['current'] += remaining

    # Crea el libro de Excel
    wb = Workbook()
    ws = wb.active
    ws.title = f"Cartera {type_filter.capitalize()} - Aging"

    # Encabezados
    headers = [
        "Tercero",
        "Moneda",
        "Total Pendiente",
        "Al Día",
        "1-30 Días Vencido",
        "31-60 Días Vencido",
        "61-90 Días Vencido",
        "+90 Días Vencido",
    ]
    ws.append(headers)

    # Aplica estilo a los encabezados
    header_font = Font(bold=True)
    for col_idx in range(1, len(headers) + 1):
        ws[f"{get_column_letter(col_idx)}1"].font = header_font
        ws[f"{get_column_letter(col_idx)}1"].fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
        ws[f"{get_column_letter(col_idx)}1"].border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

    # Ordena los datos para una salida consistente del reporte
    sorted_aging_data = sorted(third_party_aging_data.values(), key=lambda x: x['name'])

    # Agrega filas de datos
    for data in sorted_aging_data:
        row_data = [
            data['name'],
            data['currency'],
            data['total_outstanding'],
            data['current'],
            data['bucket_30'],
            data['bucket_60'],
            data['bucket_90'],
            data['bucket_plus_90'],
        ]
        ws.append(row_data)

    # Aplica formato de moneda y ajusta el ancho de las columnas
    for col_idx in range(3, len(headers) + 1):  # Columnas para montos (C a H)
        for row_idx in range(2, ws.max_row + 1):
            ws[f"{get_column_letter(col_idx)}{row_idx}"].number_format = '#,##0.00'
    
    for col in ws.columns:
        max_length = 0
        column = col[0].column  # Obtiene el número de columna
        for cell in col:
            try:
                if cell.value is not None:
                    cell_length = len(str(cell.value))
                    if cell_length > max_length:
                        max_length = cell_length
            except:
                pass
        adjusted_width = (max_length + 2) * 1.2
        ws.column_dimensions[get_column_letter(column)].width = adjusted_width

    excel_buffer = BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)

    filename = f"reporte_cartera_aging_{type_filter}_{today.isoformat()}.xlsx"
    response = HttpResponse(
        excel_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@tenant_required
@module_enabled_required("payments")
def payment_list(request):
    entries = FinancialEntry.objects.all().order_by("-entry_date")

    financial_entry_id = request.GET.get("financial_entry")
    currency = request.GET.get("currency")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    page_num = request.GET.get("page", 1)
    page_size = (
        int(request.GET.get("page_size", 25)) if request.GET.get("page_size") else 25
    )

    payments_qs = (
        Payment.objects.select_related("financial_entry", "created_by")
        .all()
        .order_by("-payment_date", "-created_at")
    )

    if financial_entry_id:
        payments_qs = payments_qs.filter(financial_entry_id=financial_entry_id)
        selected_entry = entries.filter(pk=financial_entry_id).first()
    else:
        selected_entry = None

    if currency:
        payments_qs = payments_qs.filter(currency=currency)

    if date_from:
        payments_qs = payments_qs.filter(payment_date__gte=date_from)
    if date_to:
        payments_qs = payments_qs.filter(payment_date__lte=date_to)

    # Calcular remaining_to_pay si hay un movimiento seleccionado
    remaining_to_pay = 0
    if selected_entry:
        try:
            paid_sum_in_entry_currency = Decimal("0")
            for p in Payment.objects.filter(financial_entry=selected_entry):
                paid_sum_in_entry_currency += _convert_amount(
                    p.amount, p.currency, selected_entry.currency, p.payment_date
                )
            remaining_to_pay = selected_entry.amount - paid_sum_in_entry_currency
        except ValueError:
            remaining_to_pay = selected_entry.amount
        except (ValueError, Exception):
            # Si hay error en conversión, mostrar el monto total sin restar
            remaining_to_pay = selected_entry.amount

    paginator = Paginator(payments_qs, page_size)
    payments_page = paginator.get_page(page_num)

    return render(
        request,
        "tenant/payment_list.html",
        {
            "payments": payments_page,
            "entry_choices": entries[:50],
            "currency_choices": Payment._meta.get_field("currency").choices,
            "financial_entry": selected_entry,
            "remaining_to_pay": remaining_to_pay,
        },
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def payment_create(request, entry_id):
    financial_entry = (
        FinancialEntry.objects.select_related("business").filter(pk=entry_id).first()
    )
    if not financial_entry:
        messages.error(request, "Movimiento no encontrado.")
        return redirect("financial_entry_list")

    # B4 FIX: Wrap remaining calculation to prevent 500 on missing exchange rates
    try:
        paid_sum_in_entry_currency = Decimal("0")
        for p in Payment.objects.filter(financial_entry=financial_entry):
            paid_sum_in_entry_currency += _convert_amount(
                p.amount, p.currency, financial_entry.currency, p.payment_date
            )
        remaining = financial_entry.amount - paid_sum_in_entry_currency
    except ValueError as e:
        messages.error(request, f"Error de moneda: {str(e)}")
        return redirect("payment_list")

    payments_qs = Payment.objects.filter(financial_entry=financial_entry)

    # Si ya está pagado, permitimos registrar/crear el pago faltante (auto-generación),
    # pero bloqueamos cuando esté cancelado o cuando el pendiente sea <= 0. # B4 FIX: Removed dead variables # B2 FIX: Removed duplicated function
    if financial_entry.status == FinancialEntry.CANCELLED:
        messages.info(
            request, "Este movimiento ya está cancelado."
        )
        return redirect("payment_list")

    if remaining <= 0:
        # ya no hay pendiente; solo permitimos si queremos registrar el pago faltante
        if not payments_qs.exists():
            pass
        else:
            messages.info(
                request, "Este movimiento ya está completamente conciliado."
            )
            return redirect("payment_list")


    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            # Regla pedida: si el movimiento ya está en estado PAID, garantizamos que exista al menos un Payment.
            # (Con la conciliación por estados, antes no se estaba creando ese registro.)
            if financial_entry.status == FinancialEntry.PAID and not payments_qs.exists():
                with transaction.atomic():
                    amount = form.cleaned_data["amount"]
                    payment_currency = form.cleaned_data["currency"]
                    payment_date = form.cleaned_data["payment_date"]

                    # Convertimos el monto que se guarda a moneda del movimiento.
                    amount_in_entry_currency = _convert_amount(
                        amount, payment_currency, financial_entry.currency, payment_date
                    )

                    payment = form.save(commit=False)
                    payment.financial_entry = financial_entry
                    payment.created_by = request.user
                    payment.save()

                    record_audit_event( # B4 FIX: Removed dead variables # B2 FIX: Removed duplicated function
                        request,
                        AuditEvent.CREATE,
                        "payment",
                        f"Pago auto-generado para movimiento pagado: {financial_entry.concept}",
                        entity_id=payment.pk,
                        metadata={
                            "amount": str(payment.amount),
                            "currency": payment.currency,
                            "financial_entry_id": financial_entry.pk,
                            "amount_in_entry_currency": str(amount_in_entry_currency),
                            "status": financial_entry.status,
                        },
                    )
                    _notify_payment(payment)

                messages.success(
                    request, "Pago registrado correctamente (auto-generado)."
                )
                return redirect("payment_list")

            try:
                amount = form.cleaned_data["amount"]

                payment_currency = form.cleaned_data["currency"]
                payment_date = form.cleaned_data["payment_date"]

                amount_in_entry_currency = _convert_amount(
                    amount, payment_currency, financial_entry.currency, payment_date
                )
                if amount_in_entry_currency > remaining:
                    messages.error(
                        request,
                        f"Sobre-pago no permitido. Pendiente: {remaining} {financial_entry.currency}.",
                    )
                else:
                    with transaction.atomic():
                        payment = form.save(commit=False)
                        payment.financial_entry = financial_entry
                        payment.created_by = request.user
                        payment.save()

                        # Recalcular status según total pagado
                        paid_sum_in_entry_currency_new = (
                            paid_sum_in_entry_currency + amount_in_entry_currency
                        )
                        _sync_payment_status(
                            financial_entry, paid_sum_in_entry_currency_new
                        )

                        record_audit_event(
                            request,
                            AuditEvent.CREATE,
                            "payment",
                            f"Pago registrado para: {financial_entry.concept}",
                            entity_id=payment.pk,
                            metadata={
                                "amount": str(payment.amount),
                                "currency": payment.currency,
                                "remaining_after": str(
                                    financial_entry.amount
                                    - paid_sum_in_entry_currency_new
                                ),
                                "status": financial_entry.status,
                            },
                        )
                        _notify_payment(payment)

                    messages.success(request, "Pago registrado correctamente.")
                    return redirect("payment_list")
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = PaymentForm(
            initial={"payment_date": date.today(), "currency": financial_entry.currency}
        )

    return render(
        request,
        "tenant/payment_form.html",
        {
            "form": form,
            "financial_entry": financial_entry,
            "remaining_to_pay": remaining,
        },
    )


def _sync_payment_status(financial_entry, paid_total):
    """Sincroniza cartera y factura al registrar pagos."""
    if paid_total >= financial_entry.amount:
        financial_entry.status = FinancialEntry.PAID
    elif paid_total > 0:
        financial_entry.status = FinancialEntry.PARTIAL
    else:
        financial_entry.status = FinancialEntry.PENDING
    financial_entry.save(update_fields=["status"])

    try:
        invoice = financial_entry.invoice
    except ObjectDoesNotExist:
        return

    expected_status = (
        Invoice.PAID
        if financial_entry.status == FinancialEntry.PAID
        else Invoice.ISSUED
    )
    if invoice.status != expected_status:
        invoice.status = expected_status
        invoice.save(update_fields=["status"])


def _notify_payment(payment):
    entry = payment.financial_entry
    try:
        invoice = entry.invoice
    except ObjectDoesNotExist:
        invoice = None
    link = f"/invoices/{invoice.pk}/" if invoice else "/payments/"
    notify_users(
        title="Pago registrado",
        message=f"Se registró un pago de {payment.amount} {payment.currency} para {entry.concept}.",
        link=link,
        level=Notification.SUCCESS,
        entity="payment",
        entity_id=payment.pk,
        dedupe_key=f"payment-created-{payment.pk}",
    )


@login_required
@tenant_required
@module_enabled_required("import_batch")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def generic_import_upload(request):
    business = Business.objects.first()
    if business is None:
        messages.error(request, "Primero debes crear la empresa asociada a este tenant.")
        return redirect("dashboard")

    if request.method == "POST":
        form = GenericImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                uploaded_file = form.cleaned_data["file"]
                rows = read_import_rows(uploaded_file, form.cleaned_data["delimiter"])
                with transaction.atomic():
                    batch = ImportBatch.objects.create(
                        business=business,
                        created_by=request.user,
                        file_name=uploaded_file.name[:255],
                        target_model=form.cleaned_data["target_model"],
                        status=ImportBatch.UPLOADED,
                        total_rows=len(rows),
                    )
                    ImportedRecord.objects.bulk_create([
                        ImportedRecord(batch=batch, row_data=row) for row in rows
                    ])
                    preview_batch(batch)
                    record_audit_event(request, AuditEvent.CREATE, "import_batch", f"Lote cargado y validado: {batch.file_name}", batch.pk, {"rows": len(rows), "target": batch.target_model})
                messages.success(request, f"Archivo validado: {len(rows)} filas analizadas.")
                return redirect("generic_import_preview", batch_id=batch.pk)
            except (ValidationError, ValueError) as exc:
                messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    else:
        form = GenericImportUploadForm()

    return render(request, 'tenant/generic_import_upload.html', {
        'form': form,
        'page_title': 'Importar Datos (CSV/Excel)'
    })

@login_required
@tenant_required
@module_enabled_required("import_batch")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def generic_import_preview(request, batch_id):
    batch = ImportBatch.objects.filter(pk=batch_id, business=Business.objects.first()).first()
    if not batch:
        messages.error(request, "Lote de importación no encontrado o no autorizado.")
        return redirect('generic_import_upload')

    if batch.status not in [ImportBatch.UPLOADED, ImportBatch.PREVIEWED]:
        messages.warning(request, f"Este lote ya fue {batch.status}. No se puede previsualizar de nuevo.")
        return redirect('generic_import_batch_detail', batch_id=batch.pk)

    records = batch.records.all()
    if not records.exists():
        messages.warning(request, "No hay registros para previsualizar en este lote.")
        return redirect('generic_import_upload')

    headers = list(records.first().row_data.keys()) if records.first() else []
    if batch.status == ImportBatch.UPLOADED:
        batch = preview_batch(batch)
    valid_records = records.filter(status=ImportedRecord.VALID)
    invalid_records = records.filter(status=ImportedRecord.INVALID)

    return render(request, 'tenant/generic_import_preview.html', {
        'batch': batch,
        'headers': headers,
        'valid_records': valid_records,
        'invalid_records': invalid_records,
        'page_title': f"Previsualizar Importación: {batch.file_name}"
    })

@login_required
@tenant_required
@module_enabled_required("import_batch")
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def generic_import_confirm(request, batch_id):
    batch = ImportBatch.objects.filter(pk=batch_id, business=Business.objects.first()).first()
    if not batch:
        messages.error(request, "Lote de importación no encontrado o no autorizado.")
        return redirect('generic_import_upload')

    try:
        batch = confirm_batch(batch)
        record_audit_event(request, AuditEvent.CREATE, "import_batch_confirm", f"Importación confirmada: {batch.file_name}", batch.pk, {"processed": batch.processed_rows})
        messages.success(request, f"Importación atómica completada: {batch.processed_rows} registros creados.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("generic_import_batch_detail", batch_id=batch.pk)


@login_required
@tenant_required
@module_enabled_required("import_batch")
@tenant_group_required("Administrador de empresa")
@require_POST
def generic_import_rollback(request, batch_id):
    batch = ImportBatch.objects.filter(pk=batch_id, business=Business.objects.first()).first()
    if not batch:
        messages.error(request, "Lote no encontrado.")
        return redirect("generic_import_batch_list")
    try:
        rollback_batch(batch, request.user)
        record_audit_event(request, AuditEvent.DELETE, "import_batch_rollback", f"Importación revertida: {batch.file_name}", batch.pk)
        messages.success(request, "Rollback completado; se eliminaron los registros creados por el lote.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("generic_import_batch_detail", batch_id=batch.pk)

@login_required
@tenant_required
@module_enabled_required("import_batch")
def generic_import_batch_list(request):
    batches = ImportBatch.objects.filter(business=Business.objects.first()).order_by('-created_at')
    return render(request, 'tenant/generic_import_batch_list.html', {'batches': batches, 'page_title': 'Historial de Importaciones'})

@login_required
@tenant_required
@module_enabled_required("import_batch")
def generic_import_batch_detail(request, batch_id):
    batch = ImportBatch.objects.filter(pk=batch_id, business=Business.objects.first()).first()
    if not batch:
        messages.error(request, "Lote de importación no encontrado.")
        return redirect('generic_import_batch_list')
    
    records = batch.records.all()
    headers = list(records.first().row_data.keys()) if records.first() else []

    return render(request, 'tenant/generic_import_batch_detail.html', {
        'batch': batch,
        'records': records,
        'headers': headers,
        'page_title': f"Detalle Lote {batch.pk}"
    })


@login_required
@tenant_required
@module_enabled_required("projects")
def project_list(request):
    projects = Project.objects.select_related("third_party", "owner").all()
    status = request.GET.get("status")
    project_type = request.GET.get("type")

    if status:
        projects = projects.filter(status=status)
    if project_type:
        projects = projects.filter(project_type=project_type)

    return render(
        request,
        "tenant/project_list.html",
        {
            "projects": projects,
            "status_choices": Project.STATUS_CHOICES,
            "type_choices": Project.PROJECT_TYPE_CHOICES,
            "selected_status": status or "",
            "selected_type": project_type or "",
        },
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def project_create(request):
    business = Business.objects.first()
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.business = business
        project.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "project",
            f"Proyecto creado: {project.name}",
            entity_id=project.pk,
        )
        messages.success(request, "Proyecto creado correctamente.")
        return redirect("project_list")
    return render(
        request,
        "tenant/project_form.html",
        {"form": form, "page_title": "Nuevo Proyecto", "business": business},
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def project_edit(request, project_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        messages.error(request, "Proyecto no encontrado.")
        return redirect("project_list")
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "project",
            f"Proyecto actualizado: {project.name}",
            entity_id=project.pk,
        )
        messages.success(request, "Proyecto actualizado correctamente.")
        return redirect("project_list")
    return render(
        request,
        "tenant/project_form.html",
        {
            "form": form,
            "page_title": "Editar Proyecto",
            "project": project,
            "business": project.business,
        },
    )


@login_required
@tenant_required
@module_enabled_required("chart_accounts")
def account_list(request):
    accounts = Account.objects.select_related("parent").all()
    query = request.GET.get("q", "").strip()
    account_type = request.GET.get("type", "")
    if query:
        accounts = accounts.filter(Q(code__icontains=query) | Q(name__icontains=query))
    if account_type:
        accounts = accounts.filter(account_type=account_type)
    return render(request, "tenant/account_list.html", {"accounts": accounts, "type_choices": Account.TYPE_CHOICES, "selected_type": account_type, "query": query})


@login_required
@tenant_required
@module_enabled_required("chart_accounts")
@tenant_group_required("Administrador de empresa")
def account_create(request):
    business = Business.objects.first()
    if not business:
        messages.error(request, "Primero debes crear la empresa del tenant.")
        return redirect("dashboard")
    form = AccountForm(request.POST or None, business=business)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        record_audit_event(request, AuditEvent.CREATE, "account", f"Cuenta contable creada: {account}", account.pk)
        messages.success(request, "Cuenta contable creada correctamente.")
        return redirect("account_list")
    return render(request, "tenant/account_form.html", {"form": form, "page_title": "Nueva cuenta contable"})


@login_required
@tenant_required
@module_enabled_required("chart_accounts")
@tenant_group_required("Administrador de empresa")
def account_edit(request, account_id):
    account = Account.objects.filter(pk=account_id).first()
    if not account:
        messages.error(request, "Cuenta contable no encontrada.")
        return redirect("account_list")
    form = AccountForm(request.POST or None, instance=account, business=account.business)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        record_audit_event(request, AuditEvent.UPDATE, "account", f"Cuenta contable actualizada: {account}", account.pk)
        messages.success(request, "Cuenta contable actualizada.")
        return redirect("account_list")
    return render(request, "tenant/account_form.html", {"form": form, "page_title": "Editar cuenta contable", "account": account})


@login_required
@tenant_required
@module_enabled_required("chart_accounts")
@tenant_group_required("Administrador de empresa")
@require_POST
def account_seed_puc(request):
    business = Business.objects.first()
    if not business:
        messages.error(request, "Primero debes crear la empresa del tenant.")
        return redirect("dashboard")
    with transaction.atomic():
        created, total = seed_puc_starter(business)
        record_audit_event(request, AuditEvent.CREATE, "account", f"PUC inicial cargado: {created} cuentas nuevas", metadata={"created": created, "total": total})
    messages.success(request, f"Plan inicial actualizado: {created} cuentas nuevas de {total} definidas.")
    return redirect("account_list")


@login_required
@tenant_required
def financial_category_list(request):
    categories = FinancialCategory.objects.select_related("account").all()
    return render(
        request, "tenant/financial_category_list.html", {"categories": categories}
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def financial_category_create(request):
    business = Business.objects.first()
    form = FinancialCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category = form.save(commit=False)
        category.business = business
        category.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "financial_category",
            f"Categoría creada: {category.name}",
            entity_id=category.pk,
        )
        messages.success(request, "Categoría creada correctamente.")
        return redirect("financial_category_list")
    return render(
        request,
        "tenant/financial_category_form.html",
        {"form": form, "page_title": "Nueva Categoría", "business": business},
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa")
def financial_category_edit(request, category_id):
    category = FinancialCategory.objects.filter(pk=category_id).first()
    if not category:
        messages.error(request, "Categoría no encontrada.")
        return redirect("financial_category_list")
    form = FinancialCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "financial_category",
            f"Categoría actualizada: {category.name}",
            entity_id=category.pk,
        )
        messages.success(request, "Categoría actualizada correctamente.")
        return redirect("financial_category_list")
    return render(
        request,
        "tenant/financial_category_form.html",
        {
            "form": form,
            "page_title": "Editar Categoría",
            "category": category,
            "business": category.business,
        },
    )


def _normalize_text(value: str) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _parse_csv_date(value: str, *, statement_id: int | None = None, row_index: int | None = None):
    """Intenta parsear fechas para import bancario.

    - Soporta: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    - Nunca lanza excepción; retorna None si es inválida.
    """
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            from datetime import datetime
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else datetime.strptime(value, fmt).date()
        except Exception:
            continue

    if statement_id is not None:
        logger.warning(f"[bank-import] invalid date discarded statement_id={statement_id} row_index={row_index} value={value!r}") # B3 FIX: Use Django logger # B2 FIX: Removed duplicated function
    return None



def _compute_payment_match_score(payment: Payment, fin_entry: FinancialEntry, bank_tx: BankTransaction):
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
    if bank_concept and (bank_concept == pay_concept or bank_concept in pay_concept or pay_concept in bank_concept):
        score += 25
    elif bank_concept and (bank_concept in fin_concept or fin_concept in bank_concept):
        score += 15

    return score



@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
@module_enabled_required("banking")
def bank_account_list(request):
    accounts = BankAccount.objects.select_related("business").all().order_by("name")
    return render(
        request,
        "tenant/bank_account_list.html",
        {"accounts": accounts},
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
@module_enabled_required("banking")
def bank_account_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(
            request, "Primero debes crear la empresa asociada a este tenant."
        )
        return redirect("dashboard")

    form = BankAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        bank_account = form.save(commit=False)
        bank_account.business = business
        bank_account.save()

        record_audit_event(
            request,
            AuditEvent.CREATE,
            "bank_account",
            f"Cuenta bancaria creada: {bank_account.name}",
            entity_id=bank_account.pk,
            metadata={
                "bank_account_id": str(bank_account.pk),
                "name": bank_account.name,
                "base_currency": bank_account.base_currency,
                "bank_name": bank_account.bank_name,
            },
        )
        messages.success(request, "Cuenta bancaria creada correctamente.")
        return redirect("bank_account_list")

    return render(
        request,
        "tenant/bank_account_form.html",
        {
            "form": form,
            "page_title": "Nueva cuenta bancaria",
        },
    )

@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
@module_enabled_required("banking")
def bank_account_edit(request, account_id):
    bank_account = BankAccount.objects.filter(pk=account_id).first()
    if bank_account is None:
        messages.error(request, "Cuenta bancaria no encontrada.")
        return redirect("bank_account_list")
    
    form = BankAccountForm(request.POST or None, instance=bank_account)
    if request.method == "POST" and form.is_valid():
        updated_bank_account = form.save()

        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "bank_account",
            f"Cuenta bancaria actualizada: {updated_bank_account.name}",
            entity_id=updated_bank_account.pk,
            metadata={
                "bank_account_id": str(updated_bank_account.pk),
                "name": updated_bank_account.name,
                "base_currency": updated_bank_account.base_currency,
                "bank_name": updated_bank_account.bank_name,
                "is_active": updated_bank_account.is_active,
            },
        )
        messages.success(request, "Cuenta bancaria actualizada correctamente.")
        return redirect("bank_account_list")

    return render(
        request,
        "tenant/bank_account_form.html",
        {
            "form": form,
            "page_title": "Editar cuenta bancaria",
            "bank_account": bank_account,
        },
    )

@login_required
@tenant_required
@module_enabled_required("taxes")
@tenant_group_required("Administrador de empresa")
def tax_rule_list(request):
    tax_rules = TaxRule.objects.filter(business=Business.objects.first()).order_by("name")
    return render(
        request, "tenant/tax_rule_list.html", {"tax_rules": tax_rules}
    )


@login_required
@tenant_required
@module_enabled_required("taxes")
@tenant_group_required("Administrador de empresa")
def tax_rule_create(request):
    business = Business.objects.first()
    if business is None:
        messages.error(request, "Primero debes crear la empresa asociada a este tenant.")
        return redirect("dashboard")

    form = TaxRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tax_rule = form.save(commit=False)
        tax_rule.business = business
        tax_rule.save()
        record_audit_event(
            request,
            AuditEvent.CREATE,
            "tax_rule",
            f"Regla tributaria creada: {tax_rule.name}",
            entity_id=tax_rule.pk,
        )
        messages.success(request, "Regla tributaria creada correctamente.")
        return redirect("tax_rule_list")
    return render(
        request,
        "tenant/tax_rule_form.html",
        {"form": form, "page_title": "Nueva Regla Tributaria", "business": business},
    )


@login_required
@tenant_required
@module_enabled_required("taxes")
@tenant_group_required("Administrador de empresa")
def tax_rule_edit(request, tax_rule_id):
    tax_rule = TaxRule.objects.filter(pk=tax_rule_id, business=Business.objects.first()).first()
    if not tax_rule:
        messages.error(request, "Regla tributaria no encontrada.")
        return redirect("tax_rule_list")

    form = TaxRuleForm(request.POST or None, instance=tax_rule)
    if request.method == "POST" and form.is_valid():
        tax_rule = form.save()
        record_audit_event(
            request,
            AuditEvent.UPDATE,
            "tax_rule",
            f"Regla tributaria actualizada: {tax_rule.name}",
            entity_id=tax_rule.pk,
        )
        messages.success(request, "Regla tributaria actualizada correctamente.")
        return redirect("tax_rule_list")
    return render(
        request,
        "tenant/tax_rule_form.html",
        {"form": form, "page_title": "Editar Regla Tributaria", "tax_rule": tax_rule},
    )


@login_required
@tenant_required
@module_enabled_required("invoices") # Quotes are part of invoices module
def quote_pdf(request, quote_id):
    """Generate PDF for a quote"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
            PageBreak,
        )
        from datetime import datetime
    except ImportError:
        messages.error(
            request, "ReportLab no está instalado. Instala: pip install reportlab"
        )
        return redirect("quote_detail", quote_id=quote_id)

    quote = (
        Quote.objects.select_related("business", "third_party")
        .filter(pk=quote_id)
        .first()
    )
    if quote is None:
        return redirect("quote_list")

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # Title and quote info
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#1f3a93"),
        spaceAfter=30,
    )

    elements.append(Paragraph(f"COTIZACIÓN {quote.quote_number}", title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Business and quote details
    info_data = [
        ["EMPRESA", quote.business.business_name],
        ["CLIENTE", quote.third_party.name if quote.third_party else "N/A"],
        ["FECHA EMISIÓN", quote.issue_date.strftime("%d/%m/%Y")],
        [
            "FECHA VENCIMIENTO",
            quote.due_date.strftime("%d/%m/%Y") if quote.due_date else "N/A",
        ],
        ["ESTADO", quote.get_status_display()],
    ]

    info_table = Table(info_data, colWidths=[2 * inch, 4 * inch])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(info_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Items table
    items_data = [["Descripción", "Cantidad", "Precio Unitario", "Subtotal"]]
    for item in quote.items.all():
        items_data.append(
            [
                item.description,
                str(item.quantity),
                f"${item.unit_price:.2f}",
                f"${item.subtotal:.2f}",
            ]
        )

    items_table = Table(
        items_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f9f9f9")],
                ),
            ]
        )
    )

    elements.append(items_table)
    elements.append(Spacer(1, 0.2 * inch))

    # Totals
    totals_data = [
        ["SUBTOTAL", f"${quote.subtotal:.2f} {quote.currency}"],
    ]
    for rule in quote.tax_rules.all():
        rule_amount = (quote.subtotal * rule.percentage) / Decimal("100")
        if rule.rule_type == TaxRule.IVA:
            totals_data.append([f"{rule.name} ({rule.percentage}%)", f"${rule_amount:.2f}"])
        elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
            totals_data.append([f"{rule.name} ({rule.percentage}%)", f"-${rule_amount:.2f}"])
    totals_data.append(["TOTAL", f"${quote.total:.2f} {quote.currency}"])

    totals_table = Table(totals_data, colWidths=[3.5 * inch, 2.5 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, len(totals_data)-1), (-1, len(totals_data)-1), "Helvetica-Bold"),
                ("FONTSIZE", (0, len(totals_data)-1), (-1, len(totals_data)-1), 12),
                ("BACKGROUND", (0, len(totals_data)-1), (-1, len(totals_data)-1), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, len(totals_data)-1), (-1, len(totals_data)-1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(totals_table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="quote_{quote.quote_number}.pdf"'
    )
    return response


@login_required
@tenant_required
@module_enabled_required("credit_notes")
def credit_note_pdf(request, credit_note_id):
    """Generate PDF for a credit note"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
            PageBreak,
        )
        from datetime import datetime
    except ImportError:
        messages.error(
            request, "ReportLab no está instalado. Instala: pip install reportlab"
        )
        return redirect("credit_note_detail", credit_note_id=credit_note_id)

    credit_note = (
        CreditNote.objects.select_related("business", "third_party", "invoice")
        .filter(pk=credit_note_id)
        .first()
    )
    if credit_note is None:
        return redirect("credit_note_list")

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # Title and credit note info
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#1f3a93"),
        spaceAfter=30,
    )

    elements.append(Paragraph(f"NOTA DE CRÉDITO {credit_note.credit_note_number}", title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Business and credit note details
    info_data = [
        ["EMPRESA", credit_note.business.business_name],
        ["CLIENTE", credit_note.third_party.name if credit_note.third_party else "N/A"],
        ["FACTURA ASOCIADA", credit_note.invoice.invoice_number if credit_note.invoice else "N/A"],
        ["FECHA EMISIÓN", credit_note.issue_date.strftime("%d/%m/%Y")],
        ["ESTADO", credit_note.get_status_display()],
    ]

    info_table = Table(info_data, colWidths=[2 * inch, 4 * inch])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(info_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Items table
    items_data = [["Descripción", "Cantidad", "Precio Unitario", "Subtotal"]]
    for item in credit_note.items.all():
        items_data.append(
            [
                item.description,
                str(item.quantity),
                f"${item.unit_price:.2f}",
                f"${item.subtotal:.2f}",
            ]
        )

    items_table = Table(
        items_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f9f9f9")],
                ),
            ]
        )
    )

    elements.append(items_table)
    elements.append(Spacer(1, 0.2 * inch))

    # Totals
    totals_data = [
        ["SUBTOTAL", f"${credit_note.subtotal:.2f} {credit_note.currency}"],
    ]
    for rule in credit_note.tax_rules.all():
        if rule.rule_type == TaxRule.IVA:
            totals_data.append([f"{rule.name} ({rule.percentage}%)", f"${credit_note.tax_amount:.2f}"])
        elif rule.rule_type in [TaxRule.RETENCION_FUENTE, TaxRule.RETENCION_ICA]:
            totals_data.append([f"{rule.name} ({rule.percentage}%)", f"-${credit_note.retention_amount:.2f}"])
    totals_data.append(["TOTAL", f"${credit_note.total:.2f} {credit_note.currency}"])

    totals_table = Table(totals_data, colWidths=[3.5 * inch, 2.5 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, len(totals_data)-1), (-1, len(totals_data)-1), "Helvetica-Bold"),
                ("FONTSIZE", (0, len(totals_data)-1), (-1, len(totals_data)-1), 12),
                ("BACKGROUND", (0, len(totals_data)-1), (-1, len(totals_data)-1), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, len(totals_data)-1), (-1, len(totals_data)-1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )

    elements.append(totals_table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="credit_note_{credit_note.credit_note_number}.pdf"'
    )
    return response

@login_required
@tenant_required
@module_enabled_required("banking")
def bank_statement_list(request):
    """Lista de extractos bancarios importados."""
    statements = BankStatement.objects.select_related("bank_account").all().order_by("-imported_at")
    return render(
        request,
        "tenant/bank_statement_list.html",
        {"statements": statements, "page_title": "Extractos Bancarios"},
    )


@login_required
@tenant_required
@module_enabled_required("banking")
def reconciliation_list(request):
    """Dashboard de conciliaciones entre extractos y movimientos."""
    from tenantdata.models import Reconciliation
    
    confirmed = Reconciliation.objects.select_related("bank_transaction").filter(
        status=Reconciliation.CONFIRMED
    ).order_by("-matched_at", "-id")[:20]
    proposed = Reconciliation.objects.select_related("bank_transaction").filter(
        status=Reconciliation.PROPOSED
    ).order_by("-created_at")
    rejected = Reconciliation.objects.select_related("bank_transaction").filter(
        status=Reconciliation.REJECTED
    ).order_by("-id")[:20]
    
    total_confirmed = sum(
        (r.bank_transaction.amount for r in confirmed if r.bank_transaction),
        Decimal("0.00"),
    )
    total_proposed = sum(
        (r.bank_transaction.amount for r in proposed if r.bank_transaction),
        Decimal("0.00"),
    )
    
    return render(
        request,
        "tenant/reconciliation_list.html",
        {
            "confirmed": confirmed,
            "proposed": proposed,
            "rejected": rejected,
            "total_confirmed": total_confirmed,
            "total_proposed": total_proposed,
            "page_title": "Conciliación Bancaria",
        },
    )


@login_required
@tenant_required
@module_enabled_required("debit_notes")
def debit_note_pdf(request, debit_note_id):
    from .services.note_pdf import debit_note_pdf as render_pdf

    note = DebitNote.objects.select_related("business", "third_party", "invoice").prefetch_related("items").filter(pk=debit_note_id).first()
    if note is None:
        raise Http404("Nota de débito no encontrada.")
    document = render_pdf(note)
    record_audit_event(request, AuditEvent.ACCESS, "debit_note", f"PDF de nota de débito: {note.debit_note_number}", entity_id=note.pk)
    return FileResponse(document, as_attachment=True, filename=f"debit_note_{note.debit_note_number}.pdf", content_type="application/pdf")
