import hashlib
import json

from django.conf import settings
from django.db import connection
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework import mixins, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from tenantdata.models import (
    APIIdempotencyRecord,
    AuditEvent,
    CurrencyRate,
    FinancialEntry,
    ThirdParty,
    WebhookDelivery,
    WebhookEndpoint,
)
from businessmanagement.serializers import (
    FinancialEntrySerializer,
    ThirdPartySerializer,
    WebhookDeliverySerializer,
    WebhookEndpointSerializer,
)


def _is_tenant_schema():
    return connection.schema_name != settings.PUBLIC_SCHEMA_NAME


class TenantAPIWritePermission(BasePermission):
    elevated_groups = ("Administrador de empresa", "Operador financiero")

    def has_permission(self, request, view):
        tenant = getattr(request, "tenant", None)
        if (
            not request.user.is_authenticated
            or not _is_tenant_schema()
            or tenant is None
            or getattr(tenant, "schema_name", settings.PUBLIC_SCHEMA_NAME)
            != connection.schema_name
        ):
            return False

        module = getattr(view, "required_module", None)
        if module and not tenant.is_module_enabled(module):
            return False

        needs_elevated_access = (
            getattr(view, "restricted_api", False)
            or request.method not in ("GET", "HEAD", "OPTIONS")
        )
        if needs_elevated_access and not (
            request.user.groups.filter(name__in=self.elevated_groups).exists()
        ):
            return False
        return True


class APIPageNumberPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class IdempotentCreateMixin:
    def create(self, request, *args, **kwargs):
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key or len(idempotency_key) > 255:
            return Response(
                {"detail": "Envía una cabecera Idempotency-Key de hasta 255 caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fingerprint = hashlib.sha256(
            json.dumps(request.data, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        with transaction.atomic():
            try:
                with transaction.atomic():
                    record = APIIdempotencyRecord.objects.create(
                        user=request.user,
                        key=idempotency_key,
                        request_fingerprint=fingerprint,
                    )
                    is_new = True
            except IntegrityError:
                record = APIIdempotencyRecord.objects.get(
                    user=request.user, key=idempotency_key
                )
                is_new = False

            if not is_new:
                if record.request_fingerprint != fingerprint:
                    return Response(
                        {"detail": "La clave ya fue usada con otra solicitud."},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(record.response_body, status=record.response_status)

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            record.response_status = status.HTTP_201_CREATED
            record.response_body = serializer.data
            record.save(update_fields=("response_status", "response_body"))
            return Response(serializer.data, status=status.HTTP_201_CREATED)


class FinancialEntryViewSet(
    IdempotentCreateMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    serializer_class = FinancialEntrySerializer
    pagination_class = APIPageNumberPagination
    permission_classes = (TenantAPIWritePermission,)
    required_module = "finances"
    queryset = FinancialEntry.objects.select_related(
        "business", "project", "category", "third_party", "created_by"
    )

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter, field in (
            ("type", "entry_type"),
            ("status", "status"),
            ("currency", "currency"),
        ):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(entry_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(entry_date__lte=date_to)
        return queryset

    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.CREATE,
            entity="financial_entry",
            entity_id=str(entry.pk),
            summary=f"Movimiento creado por API: {entry.concept}",
        )

    def perform_update(self, serializer):
        entry = serializer.save()
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.UPDATE,
            entity="financial_entry",
            entity_id=str(entry.pk),
            summary=f"Movimiento actualizado por API: {entry.concept}",
        )


class ThirdPartyViewSet(
    IdempotentCreateMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    serializer_class = ThirdPartySerializer
    pagination_class = APIPageNumberPagination
    permission_classes = (TenantAPIWritePermission,)
    required_module = "third_parties"
    queryset = ThirdParty.objects.all()

    def perform_create(self, serializer):
        third_party = serializer.save()
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.CREATE,
            entity="third_party",
            entity_id=str(third_party.pk),
            summary=f"Tercero creado por API: {third_party.name}",
        )

    def perform_update(self, serializer):
        third_party = serializer.save()
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.UPDATE,
            entity="third_party",
            entity_id=str(third_party.pk),
            summary=f"Tercero actualizado por API: {third_party.name}",
        )


class WebhookEndpointViewSet(
    IdempotentCreateMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    serializer_class = WebhookEndpointSerializer
    pagination_class = APIPageNumberPagination
    permission_classes = (TenantAPIWritePermission,)
    restricted_api = True
    required_module = "audit"
    queryset = WebhookEndpoint.objects.all()

    def perform_create(self, serializer):
        endpoint = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.CREATE,
            entity="webhook_endpoint",
            entity_id=str(endpoint.pk),
            summary=f"Endpoint webhook creado por API: {endpoint.name}",
            metadata={"events": endpoint.event_types},
        )

    def perform_update(self, serializer):
        endpoint = serializer.save()
        AuditEvent.objects.create(
            actor=self.request.user,
            action=AuditEvent.UPDATE,
            entity="webhook_endpoint",
            entity_id=str(endpoint.pk),
            summary=f"Endpoint webhook actualizado por API: {endpoint.name}",
            metadata={"events": endpoint.event_types, "active": endpoint.is_active},
        )


class WebhookDeliveryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    GenericViewSet,
):
    serializer_class = WebhookDeliverySerializer
    pagination_class = APIPageNumberPagination
    permission_classes = (TenantAPIWritePermission,)
    restricted_api = True
    required_module = "audit"
    queryset = WebhookDelivery.objects.select_related("endpoint")

    def get_queryset(self):
        queryset = super().get_queryset()
        event = self.request.query_params.get("event")
        delivery_status = self.request.query_params.get("status")
        if event:
            queryset = queryset.filter(event=event)
        if delivery_status:
            queryset = queryset.filter(status=delivery_status)
        return queryset


@api_view(['GET'])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@require_GET
def financial_entries_api(request):
    if not _is_tenant_schema():
        return JsonResponse({'error': 'API disponible solo en contexto tenant'}, status=403)
    if not request.tenant.is_module_enabled("finances"):
        return JsonResponse({'error': 'Módulo no habilitado para esta empresa'}, status=403)

    qs = FinancialEntry.objects.select_related('third_party', 'created_by').all()
    entry_type = request.GET.get('type')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    currency = request.GET.get('currency')

    if entry_type:
        qs = qs.filter(entry_type=entry_type)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(entry_date__gte=date_from)
    if date_to:
        qs = qs.filter(entry_date__lte=date_to)
    if currency:
        qs = qs.filter(currency=currency)

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 25))
    paginator = Paginator(qs.order_by('-entry_date', '-created_at'), page_size)
    pg = paginator.get_page(page)

    results = []
    for e in pg:
        results.append({
            'id': e.pk,
            'concept': e.concept,
            'amount': str(e.amount),
            'currency': e.currency,
            'entry_type': e.entry_type,
            'status': e.status,
            'entry_date': e.entry_date.isoformat(),
            'third_party': e.third_party.name if e.third_party else None,
            'created_by': e.created_by.username if e.created_by else None,
        })

    return JsonResponse({'count': paginator.count, 'num_pages': paginator.num_pages, 'page': pg.number, 'results': results})


@api_view(['GET'])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@require_GET
def third_parties_api(request):
    if not _is_tenant_schema():
        return JsonResponse({'error': 'API disponible solo en contexto tenant'}, status=403)
    if not request.tenant.is_module_enabled("third_parties"):
        return JsonResponse({'error': 'Módulo no habilitado para esta empresa'}, status=403)
    qs = ThirdParty.objects.filter(is_active=True).order_by('name')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 50))
    paginator = Paginator(qs, page_size)
    pg = paginator.get_page(page)
    results = []
    for t in pg:
        results.append({'id': t.pk, 'name': t.name, 'email': t.email, 'phone': t.phone, 'type': t.third_party_type})
    return JsonResponse({'count': paginator.count, 'num_pages': paginator.num_pages, 'page': pg.number, 'results': results})


@api_view(['GET'])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@require_GET
def currency_rates_api(request):
    if not _is_tenant_schema():
        return JsonResponse({'error': 'API disponible solo en contexto tenant'}, status=403)
    if not request.tenant.is_module_enabled("currency_rates"):
        return JsonResponse({'error': 'Módulo no habilitado para esta empresa'}, status=403)
    qs = CurrencyRate.objects.order_by('-rate_date', 'currency')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 25))
    paginator = Paginator(qs, page_size)
    pg = paginator.get_page(page)
    results = []
    for r in pg:
        results.append({'id': r.pk, 'currency': r.currency, 'rate_date': r.rate_date.isoformat(), 'rate': str(r.rate_to_local), 'source': r.source})
    return JsonResponse({'count': paginator.count, 'num_pages': paginator.num_pages, 'page': pg.number, 'results': results})
