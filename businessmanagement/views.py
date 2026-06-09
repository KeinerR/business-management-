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
from django.db import connection, transaction
from django.db.models import Count, Sum, Q
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
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
    QuoteItem,
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
    InvoiceItemForm,
    QuoteForm,
    PaymentForm,
    ProjectForm,
    FinancialCategoryForm,
    MODULES_INDIVIDUAL,
    MODULES_BUSINESS,
    BankStatementImportCSVForm,
    ReconciliationConfirmForm,
    BankAccountForm,
)
from .models import Domain, Tenant

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
    business = Business.objects.first()
    employee_count = Employee.objects.count()
    user_count = get_user_model().objects.count()
    third_party_count = ThirdParty.objects.filter(is_active=True).count()
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
    return render(
        request,
        "dashboard.html",
        {
            "business": business,
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
        },
    )


@login_required
@platform_required
def platform_dashboard(request):
    tenants = Tenant.objects.exclude(
        schema_name=settings.PUBLIC_SCHEMA_NAME
    ).prefetch_related("domains")
    tenant_count = tenants.count()
    domain_count = Domain.objects.exclude(
        tenant__schema_name=settings.PUBLIC_SCHEMA_NAME
    ).count()
    primary_domains = Domain.objects.filter(is_primary=True).exclude(
        tenant__schema_name=settings.PUBLIC_SCHEMA_NAME
    )
    public_domain_count = Domain.objects.filter(
        tenant__schema_name=settings.PUBLIC_SCHEMA_NAME
    ).count()
    tenant_snapshots = []
    for tenant in tenants.order_by("-created_on")[:6]:
        snapshot = {
            "tenant": tenant,
            "employee_count": None,
            "entry_count": None,
            "latest_activity": None,
            "status": "Sin migrar",
        }
        try:
            with schema_context(tenant.schema_name):
                snapshot["employee_count"] = Employee.objects.count()
                snapshot["entry_count"] = FinancialEntry.objects.count()
                snapshot["latest_activity"] = AuditEvent.objects.first()
                snapshot["status"] = "Operativo"
        except Exception:
            connection.set_schema_to_public()
        tenant_snapshots.append(snapshot)
    return render(
        request,
        "platform/dashboard.html",
        {
            "tenant_count": tenant_count,
            "domain_count": domain_count,
            "public_domain_count": public_domain_count,
            "primary_domains": primary_domains[:6],
            "tenant_snapshots": tenant_snapshots,
        },
    )


@login_required
@platform_required
def platform_tenant_list(request):
    tenants = (
        Tenant.objects.exclude(schema_name=settings.PUBLIC_SCHEMA_NAME)
        .prefetch_related("domains")
        .order_by("name")
    )
    return render(request, "platform/tenant_list.html", {"tenants": tenants})


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
        rate = form.save()
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
        rate = form.save()
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


@login_required
def create_business(request):
    return redirect_platform_managed_section(request)


@login_required
def business_list(request):
    return redirect_platform_managed_section(request)


@login_required
@tenant_required
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


@login_required
@tenant_required
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
            items_data = request.POST.getlist("item_description")
            quantities = request.POST.getlist("item_quantity")
            prices = request.POST.getlist("item_price")

            try:
                with transaction.atomic():
                    invoice.save()
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            InvoiceItem.objects.create(
                                invoice=invoice,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    invoice.calculate_totals(subtotal)
                    invoice.save()

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
            except InvalidOperation:
                messages.error(request, "Error al crear factura: cantidad o precio inválido.")
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
@tenant_group_required("Administrador de empresa", "Operador financiero")
def invoice_edit(request, invoice_id):
    invoice = Invoice.objects.select_related("business").filter(pk=invoice_id).first()
    if invoice is None:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")

    tenant_type = getattr(request.tenant, "tenant_type", Tenant.TYPE_BUSINESS)
    if request.method == "POST":
        form = InvoiceForm(request.POST, instance=invoice, tenant_type=tenant_type)
        if form.is_valid():
            invoice = form.save(commit=False)

            # Limpiar items anteriores y crear nuevos
            invoice.items.all().delete()
            items_data = request.POST.getlist("item_description")
            quantities = request.POST.getlist("item_quantity")
            prices = request.POST.getlist("item_price")

            try:
                with transaction.atomic():
                    invoice.save()
                    subtotal = Decimal("0")

                    for desc, qty, price in zip(items_data, quantities, prices):
                        if desc and qty and price:
                            qty_dec = Decimal(qty)
                            price_dec = Decimal(price)
                            item_subtotal = qty_dec * price_dec
                            InvoiceItem.objects.create(
                                invoice=invoice,
                                description=desc,
                                quantity=qty_dec,
                                unit_price=price_dec,
                                subtotal=item_subtotal,
                            )
                            subtotal += item_subtotal

                    invoice.calculate_totals(subtotal)
                    invoice.save()

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
            except InvalidOperation:
                messages.error(request, "Error al actualizar factura: cantidad o precio inválido.")
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
        ["IVA ({0}%)".format(invoice.tax_percentage), f"${invoice.tax_amount:.2f}"],
        ["TOTAL", f"${invoice.total:.2f} {invoice.currency}"],
    ]

    totals_table = Table(totals_data, colWidths=[3.5 * inch, 2.5 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("FONTSIZE", (0, 2), (-1, 2), 12),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#1f3a93")),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.whitesmoke),
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
@tenant_group_required("Administrador de empresa", "Operador financiero")
@require_POST
def invoice_delete(request, invoice_id):
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        messages.error(request, "Factura no encontrada.")
        return redirect("invoice_list")

    invoice_number = invoice.invoice_number
    invoice.delete()

    record_audit_event(
        request,
        AuditEvent.DELETE,
        "invoice",
        f"Factura eliminada: {invoice_number}",
        entity_id=invoice_id,
    )
    messages.success(request, "Factura eliminada correctamente.")
    return redirect("invoice_list")


@login_required
@tenant_required
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

                quote.calculate_totals(subtotal)
                quote.save()

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
def quote_detail(request, quote_id):
    quote = (
        Quote.objects.select_related("business", "project", "third_party", "created_by")
        .filter(pk=quote_id)
        .first()
    )
    if quote is None:
        messages.error(request, "Cotización no encontrada.")
        return redirect("quote_list")
    return render(request, "tenant/quote_detail.html", {"quote": quote})


@login_required
@tenant_required
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

    messages.success(request, "Cotización aceptada correctamente.")
    return redirect("quote_detail", quote_id=quote.pk)


def _convert_quote_to_invoice(quote: Quote, created_by_user):
    """
    Crea Invoice + InvoiceItems + FinancialEntry para cartera.
    Idempotencia: si quote ya tiene converted_invoice o financial_entry, reutiliza/evita duplicar.
    """
    if quote.status != Quote.ACCEPTED:
        raise ValueError("Solo se puede convertir una cotización aceptada.")

    if quote.converted_invoice_id and quote.financial_entry_id:
        # ya convertido
        return quote.converted_invoice, quote.financial_entry

    # Evitar duplicados parciales
    if quote.converted_invoice_id:
        invoice = quote.converted_invoice
        financial_entry = quote.financial_entry
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
            tax_percentage=quote.tax_percentage,
            currency=quote.currency,
            created_by=created_by_user,
        )
        # subtotal/totals
        invoice.calculate_totals(quote.subtotal)
        invoice.save()

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
        invoice.save()

        # FinancialEntry
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

        quote.converted_invoice = invoice
        quote.financial_entry = financial_entry
        quote.status = Quote.CONVERTED
        quote.save(update_fields=["converted_invoice", "financial_entry", "status"])

        # enlazar invoice -> financial_entry (OneToOne)
        invoice.financial_entry = financial_entry
        invoice.save(update_fields=["financial_entry"])

    return quote.converted_invoice, quote.financial_entry


@login_required
@tenant_required
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


def _convert_amount(amount, from_currency, to_currency, rate_date):
    if from_currency == to_currency:
        return amount

    # suponemos que rate_to_local representa el valor de 1 unidad de currency en moneda local (COP)
    from_rate = CurrencyRate.objects.filter(
        currency=from_currency, rate_date=rate_date
    ).first()
    to_rate = CurrencyRate.objects.filter(
        currency=to_currency, rate_date=rate_date
    ).first()

    if not from_rate or not to_rate:
        raise ValueError(
            "No existe tasa de cambio para la fecha y monedas seleccionadas."
        )

    # amount_local = amount * from_rate.rate_to_local
    amount_local = amount * from_rate.rate_to_local
    # amount_in_to = amount_local / to_rate.rate_to_local
    return amount_local / to_rate.rate_to_local


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

    for e in entries_qs.select_related("third_party", "project"):
        remaining = compute_remaining(e)
        if remaining <= 0:
            continue

        is_overdue = bool(e.due_date and e.due_date < today)
        is_next_due = bool(
            e.due_date and due_from <= e.due_date <= due_to
        )  # incluye hoy

        row = {
            "entry_id": e.id,
            "concept": e.concept,
            "third_party": e.third_party,
            "third_party_id": e.third_party_id,
            "project_name": e.project.name if e.project else None,
            "due_date": e.due_date,
            "currency": e.currency,
            "remaining": remaining,
            "is_overdue": is_overdue,
            "is_next_due": is_next_due,
        }
        entry_rows.append(row)

        remaining_total += remaining
        if is_overdue:
            overdue_total += remaining
            overdue_count += 1
        if is_next_due:
            next_due_total += remaining
            next_due_count += 1

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

    for r in entry_rows:
        tp_id = r["third_party_id"]
        if not tp_id:
            continue
        remaining_total_by_tp[tp_id] = remaining_total_by_tp.get(tp_id, Decimal("0")) + r["remaining"]
        if r["is_overdue"]:
            overdue_total_by_tp[tp_id] = overdue_total_by_tp.get(tp_id, Decimal("0")) + r["remaining"]
            overdue_count_by_tp[tp_id] = overdue_count_by_tp.get(tp_id, 0) + 1
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

        third_party_rows.append(
            {
                "third_party": tp,
                "remaining_total": remaining_total_by_tp.get(tp_id, Decimal("0")),
                "overdue_total": overdue_total_by_tp.get(tp_id, Decimal("0")),
                "next_due_total": next_due_total_by_tp.get(tp_id, Decimal("0")),
                "overdue_count": overdue_count_by_tp.get(tp_id, 0),
                "next_due_count": next_due_count_by_tp.get(tp_id, 0),
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
    }
    return render(request, "tenant/cartera_dashboard.html", context)


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
            paid_sum_in_entry_currency = 0
            for p in Payment.objects.filter(financial_entry=selected_entry):
                paid_sum_in_entry_currency += _convert_amount(
                    p.amount, p.currency, selected_entry.currency, p.payment_date
                )
            remaining_to_pay = selected_entry.amount - paid_sum_in_entry_currency
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
    if financial_entry is None:
        messages.error(request, "Movimiento no encontrado.")
        return redirect("financial_entry_list")

    # Si el movimiento está cancelado o ya está pagado, no permitir
    total_paid_local = financial_entry.amount

    payments_qs = Payment.objects.filter(financial_entry=financial_entry)
    paid_sum = payments_qs.aggregate(total=Sum("amount"))["total"] or 0

    # Nota: con conversión real, paid_sum está en distintas monedas, por eso calculamos en moneda del movimiento usando conversion por fecha.
    paid_sum_in_entry_currency = 0
    for p in payments_qs:
        paid_sum_in_entry_currency += _convert_amount(
            p.amount, p.currency, financial_entry.currency, p.payment_date
        )

    remaining = financial_entry.amount - paid_sum_in_entry_currency

    # Si ya está pagado, permitimos registrar/crear el pago faltante (auto-generación),
    # pero bloqueamos cuando esté cancelado o cuando el pendiente sea <= 0.
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

                    record_audit_event(
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
                        if paid_sum_in_entry_currency_new >= financial_entry.amount:
                            financial_entry.status = FinancialEntry.PAID
                        elif paid_sum_in_entry_currency_new > 0:
                            financial_entry.status = FinancialEntry.PARTIAL
                        else:
                            financial_entry.status = FinancialEntry.PENDING

                        financial_entry.save(update_fields=["status"])

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
def financial_category_list(request):
    categories = FinancialCategory.objects.all()
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


def _parse_csv_date(value: str):
    # MVP tolerante: intenta YYYY-MM-DD y DD/MM/YYYY
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else date.strptime(value, fmt)
        except Exception:
            pass
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
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_statement_import_csv(request):
    if request.method == "POST":
        form = BankStatementImportCSVForm(request.POST, request.FILES)
        if form.is_valid():
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

            import io
            import csv as csv_lib

            raw = uploaded.read()
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("latin-1")
            try:
                uploaded.seek(0)
            except Exception:
                pass

            f = io.StringIO(text)
            if has_header:
                reader = csv_lib.DictReader(f, delimiter=delimiter)
                for row in reader:
                    date_val = row.get("date") or row.get("fecha")
                    amount_val = row.get("amount") or row.get("monto")
                    currency_val = row.get("currency") or row.get("moneda") or bank_account.base_currency
                    desc_val = row.get("description") or row.get("concept") or row.get("detalle") or ""
                    external_id = row.get("external_id") or row.get("reference") or row.get("ref") or ""

                    tx_date = _parse_csv_date(date_val)
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
                        description=desc_val[:255],
                        concept=_normalize_text(desc_val)[:255],
                        amount=amount_dec,
                        currency=currency,
                        external_id=external_id[:120],
                        direction="",
                        status=BankTransaction.IMPORTED,
                    )
            else:
                messages.error(request, "CSV sin encabezado no soportado en este MVP. Agrega header.")
                statement.delete()
                return redirect("bank_statement_import_csv")

            messages.success(request, f"Extracto importado: {statement_name}.")
            return redirect("bank_transaction_suggestions", statement_id=statement.pk)
    else:
        form = BankStatementImportCSVForm()

    return render(
        request,
        "tenant/bank_statement_import.html",
        {"form": form, "page_title": "Importar extracto CSV"},
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_transaction_suggestions(request, statement_id):
    statement = BankStatement.objects.filter(pk=statement_id).first()
    if not statement:
        messages.error(request, "Extracto no encontrado.")
        return redirect("dashboard")

    txs = statement.transactions.all().order_by("transaction_date", "created_at")

    reconciliations = []
    for tx in txs:
        from_date = tx.transaction_date - timedelta(days=3)
        to_date = tx.transaction_date + timedelta(days=3)

        payments_qs = Payment.objects.select_related("financial_entry", "created_by").filter(
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
@require_POST
def reconciliation_confirm(request, rec_id):
    rec = Reconciliation.objects.filter(pk=rec_id).first()
    if not rec:
        messages.error(request, "Conciliación no encontrada.")
        return redirect("dashboard")

    form = ReconciliationConfirmForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Datos inválidos.")
        return redirect("bank_transaction_suggestions", statement_id=rec.bank_transaction.statement_id)

    action = form.cleaned_data["action"]

    if action == "reject":
        rec.status = Reconciliation.REJECTED
        rec.save(update_fields=["status"])
        messages.success(request, "Rechazado.")
        return redirect("bank_transaction_suggestions", statement_id=rec.bank_transaction.statement_id)

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
    return redirect("bank_transaction_suggestions", statement_id=rec.bank_transaction.statement_id)


def _normalize_text(value: str) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _parse_csv_date(value: str):
    # MVP tolerante: intenta YYYY-MM-DD y DD/MM/YYYY
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else date.strptime(value, fmt)
        except Exception:
            pass
    return None


def _compute_payment_match_score(payment: Payment, fin_entry: FinancialEntry, bank_tx: BankTransaction):
    score = 0

    # Fecha cercana (+)
    delta_days = abs((payment.payment_date - bank_tx.transaction_date).days)
    if delta_days == 0:
        score += 50
    elif delta_days <= 1:
        score += 35
    elif delta_days <= 3:
        score += 20
    elif delta_days <= 7:
        score += 10

    # Monto exacto (+) - MVP exige misma moneda, por lo que ya debería coincidir
    if payment.currency == bank_tx.currency:
        if payment.amount == bank_tx.amount:
            score += 50
        else:
            # tolerancia decimal mínima
            try:
                diff = abs(payment.amount - bank_tx.amount)
                if diff <= 0.01:
                    score += 40
            except Exception:
                pass

    # Concepto (+)
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
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_statement_import_csv(request):
    """
    MVP:
    - POST: sube CSV -> crea BankStatement y BankTransaction
    - CSV header esperado (flexible por nombres):
      date/fecha, amount/monto, currency/moneda, description/concept/detalle, external_id/reference/ref (opcional)
    """
    if request.method == "POST":
        form = BankStatementImportCSVForm(request.POST, request.FILES)
        if form.is_valid():
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

            import io
            import csv as csv_lib

            # Intento de decodificación UTF-8 con fallback latin-1
            raw = uploaded.read()
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("latin-1")
            uploaded.seek(0)  # no siempre necesario, pero mantenemos

            f = io.StringIO(text)
            if has_header:
                reader = csv_lib.DictReader(f, delimiter=delimiter)
                for row in reader:
                    # columnas flexibles
                    date_val = row.get("date") or row.get("fecha")
                    amount_val = row.get("amount") or row.get("monto")
                    currency_val = row.get("currency") or row.get("moneda") or bank_account.base_currency
                    desc_val = (
                        row.get("description")
                        or row.get("concept")
                        or row.get("detalle")
                        or ""
                    )
                    external_id = row.get("external_id") or row.get("reference") or row.get("ref") or ""

                    tx_date = _parse_csv_date(date_val)
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
                        description=desc_val[:255],
                        concept=_normalize_text(desc_val)[:255],
                        amount=amount_dec,
                        currency=currency,
                        external_id=external_id[:120],
                        direction="",
                        status=BankTransaction.IMPORTED,
                    )
            else:
                # Sin header: no soportado en MVP (evitamos ambigüedad)
                messages.error(request, "CSV sin encabezado no soportado en este MVP. Agrega header.")
                statement.delete()
                return redirect("bank_statement_import_csv")

            messages.success(request, f"Extracto importado: {statement_name}.")
            return redirect("bank_transaction_suggestions", statement_id=statement.pk)

    else:
        form = BankStatementImportCSVForm()

    return render(
        request,
        "tenant/bank_statement_import.html",
        {"form": form, "page_title": "Importar extracto CSV"},
    )


@login_required
@tenant_required
@module_enabled_required("finances")
@tenant_group_required("Administrador de empresa", "Operador financiero")
def bank_transaction_suggestions(request, statement_id):
    statement = BankStatement.objects.filter(pk=statement_id).first()
    if not statement:
        messages.error(request, "Extracto no encontrado.")
        return redirect("dashboard")

    # Necesitamos candidates por payment para el tenant
    txs = statement.transactions.all().order_by("transaction_date", "created_at")

    reconciliations = []
    # Generamos propuestas por transacción vs pagos en ventana ±3 días y misma currency
    for tx in txs:
        from_date = tx.transaction_date - timedelta(days=3)
        to_date = tx.transaction_date + timedelta(days=3)

        payments_qs = (
            Payment.objects.select_related("financial_entry", "created_by")
            .filter(
                payment_date__gte=from_date,
                payment_date__lte=to_date,
                currency=tx.currency,
            )
        )

        best = []
        for p in payments_qs:
            fin_entry = p.financial_entry
            if not fin_entry:
                continue

            score = 0
            # MVP: monto exacto en misma currency
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
            rec, _created = Reconciliation.objects.get_or_create(
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
            if not _created:
                # actualizamos confidence si aplica
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
@require_POST
def reconciliation_confirm(request, rec_id):
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

    # confirm
    if rec.status != Reconciliation.CONFIRMED:
        rec.status = Reconciliation.CONFIRMED
        rec.matched_at = date.today()
        rec.updated_at = date.today()
        rec.save(update_fields=["status", "matched_at", "updated_at"])

    # MVP: crear Payment si falta (según decisión previa)
    if not rec.payment and rec.financial_entry:
        fin_entry = rec.financial_entry
        # crea payment en moneda y fecha del banco, usando monto del tx
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
        "bank_transaction_suggestions", statement_id=rec.bank_transaction.statement_id
    )


@login_required
@tenant_required
@tenant_group_required("Administrador de empresa", "Operador financiero")
@module_enabled_required("finances")
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
@module_enabled_required("finances")
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
