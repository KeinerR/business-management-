"""Tenant-local conversion. COP is the base; rates are exact for the payment date."""
from decimal import Decimal

from tenantdata.models import CurrencyRate


def convert_amount(amount, from_currency, to_currency, rate_date):
    if from_currency == to_currency:
        return amount

    def rate(currency):
        if currency == 'COP':
            return Decimal('1')
        record = CurrencyRate.objects.filter(currency=currency, rate_date=rate_date).first()
        if record is None or not record.rate_to_local.is_finite() or record.rate_to_local <= 0:
            raise ValueError(f'Falta una tasa válida de {currency} para {rate_date:%d/%m/%Y}.')
        return record.rate_to_local

    return amount * rate(from_currency) / rate(to_currency)
