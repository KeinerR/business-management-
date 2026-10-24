"""Daily reference rates from ExchangeRate-API's open USD feed (not a fiscal TRM)."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, DecimalException, InvalidOperation

import requests
from django.utils import timezone

SOURCE = 'open.er-api.com'
URL = 'https://open.er-api.com/v6/latest/USD'


def fetch_reference_rates():
    response = requests.get(URL, timeout=(5, 20), allow_redirects=False)
    if response.status_code != 200:
        raise ValueError('El proveedor de tasas no respondió HTTP 200.')
    payload = response.json()
    if not isinstance(payload, dict) or payload.get('result') != 'success' or payload.get('base_code') != 'USD':
        raise ValueError('Respuesta de tasas inválida: se esperaba base USD.')
    try:
        updated = datetime.fromtimestamp(payload['time_last_update_unix'], tz=dt_timezone.utc)
        cop = Decimal(str(payload['rates']['COP']))
        eur = Decimal(str(payload['rates']['EUR']))
    except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
        raise ValueError('El proveedor devolvió una fecha o tasas inválidas.') from exc
    age = (timezone.now() - updated).total_seconds()
    if age < -3600 or age > 3 * 86400:
        raise ValueError('El proveedor devolvió tasas futuras o de más de tres días.')
    if any(not rate.is_finite() or rate <= 0 for rate in (cop, eur)):
        raise ValueError('Las tasas deben ser positivas y finitas.')
    try:
        rates = {'USD': cop.quantize(Decimal('.0001')), 'EUR': (cop / eur).quantize(Decimal('.0001'))}
    except DecimalException as exc:
        raise ValueError('Las tasas exceden el rango permitido.') from exc
    if any(rate <= 0 or rate >= Decimal('10000000000') for rate in rates.values()):
        raise ValueError('Las tasas exceden el rango permitido.')
    return updated.date(), rates
