from django.contrib import admin
from django.db import connection

from .models import (
    AuditEvent,
    Business,
    CurrencyRate,
    Employee,
    FinancialEntry,
    ThirdParty,
    Project,
    FinancialCategory,
    Invoice,
    InvoiceItem,
    Payment,
)


class TenantOnlyAdminMixin:
    def has_module_permission(self, request):
        return connection.schema_name != "public" and super().has_module_permission(
            request
        )


@admin.register(Business)
class BusinessAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("business_name", "business_email", "business_phone")
    search_fields = (
        "business_name",
        "business_email",
        "name_business_owner",
        "last_name_business_owner",
    )


@admin.register(Employee)
class EmployeeAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "position", "business", "user")
    search_fields = (
        "first_name",
        "last_name",
        "email",
        "position",
        "business__business_name",
        "user__username",
    )
    list_filter = ("business",)


@admin.register(ThirdParty)
class ThirdPartyAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "third_party_type", "email", "phone", "is_active")
    search_fields = ("name", "identification", "email", "phone")
    list_filter = ("third_party_type", "is_active")


@admin.register(Project)
class ProjectAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "project_type", "status", "start_date", "end_date", "owner")
    search_fields = ("name", "description")
    list_filter = ("project_type", "status")


@admin.register(FinancialCategory)
class FinancialCategoryAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "category_type", "is_active")
    search_fields = ("name",)
    list_filter = ("category_type", "is_active")


@admin.register(Payment)
class PaymentAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "payment_date",
        "concept",
        "amount",
        "currency",
        "financial_entry",
        "created_by",
    )
    search_fields = ("concept", "notes", "financial_entry__concept")
    list_filter = ("currency", "payment_date")


@admin.register(FinancialEntry)
class FinancialEntryAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "entry_date",
        "concept",
        "entry_type",
        "status",
        "amount",
        "currency",
        "project",
        "category",
    )
    search_fields = ("concept", "notes", "third_party__name")
    list_filter = (
        "entry_type",
        "status",
        "currency",
        "entry_date",
        "project",
        "category",
    )
    date_hierarchy = "entry_date"


@admin.register(Invoice)
class InvoiceAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "third_party",
        "status",
        "issue_date",
        "total",
        "project",
    )
    search_fields = ("invoice_number", "third_party__name")
    list_filter = ("status", "issue_date", "project")


@admin.register(CurrencyRate)
class CurrencyRateAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("rate_date", "currency", "rate_to_local", "source")
    search_fields = ("currency", "source")
    list_filter = ("currency", "rate_date")


@admin.register(AuditEvent)
class AuditEventAdmin(TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "entity", "summary")
    search_fields = ("summary", "entity", "entity_id", "actor__username")
    list_filter = ("action", "entity", "created_at")
    readonly_fields = (
        "actor",
        "action",
        "entity",
        "entity_id",
        "summary",
        "metadata",
        "created_at",
    )
