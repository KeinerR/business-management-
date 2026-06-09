from django.conf import settings
from django.db import connection
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from tenantdata.models import FinancialEntry, ThirdParty, CurrencyRate


def _is_tenant_schema():
    return connection.schema_name != settings.PUBLIC_SCHEMA_NAME


@api_view(['GET'])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@require_GET
def financial_entries_api(request):
    if not _is_tenant_schema():
        return JsonResponse({'error': 'API disponible solo en contexto tenant'}, status=403)

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
    qs = CurrencyRate.objects.order_by('-rate_date', 'currency')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 25))
    paginator = Paginator(qs, page_size)
    pg = paginator.get_page(page)
    results = []
    for r in pg:
        results.append({'id': r.pk, 'currency': r.currency, 'rate_date': r.rate_date.isoformat(), 'rate': str(r.rate_to_local), 'source': r.source})
    return JsonResponse({'count': paginator.count, 'num_pages': paginator.num_pages, 'page': pg.number, 'results': results})
