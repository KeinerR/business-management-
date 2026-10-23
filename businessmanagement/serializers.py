import ipaddress
from urllib.parse import urlsplit

from rest_framework import serializers

from tenantdata.models import (
    Business,
    FinancialEntry,
    ThirdParty,
    WebhookDelivery,
    WebhookEndpoint,
)


class ThirdPartySerializer(serializers.ModelSerializer):
    class Meta:
        model = ThirdParty
        fields = (
            "id",
            "name",
            "identification",
            "email",
            "phone",
            "address",
            "third_party_type",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class FinancialEntrySerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(queryset=Business.objects.all())

    class Meta:
        model = FinancialEntry
        fields = (
            "id",
            "business",
            "project",
            "category",
            "third_party",
            "entry_type",
            "status",
            "concept",
            "amount",
            "currency",
            "entry_date",
            "due_date",
            "notes",
            "personal",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        business = attrs.get("business", getattr(self.instance, "business", None))
        for field_name in ("project", "category"):
            related = attrs.get(field_name, getattr(self.instance, field_name, None))
            if related is not None and business is not None and related.business_id != business.pk:
                raise serializers.ValidationError(
                    {field_name: "El registro relacionado debe pertenecer a la misma empresa."}
                )
        return attrs


class WebhookEndpointSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True, trim_whitespace=False, required=False)
    event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=WebhookEndpoint.EVENT_CHOICES),
        allow_empty=False,
    )

    class Meta:
        model = WebhookEndpoint
        fields = (
            "id",
            "name",
            "url",
            "secret",
            "event_types",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate_url(self, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise serializers.ValidationError("Los webhooks solo admiten URLs HTTPS.")
        hostname = parsed.hostname.lower()
        if parsed.username or parsed.password:
            raise serializers.ValidationError("No incluyas credenciales en la URL del webhook.")
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise serializers.ValidationError("No se permiten destinos locales.")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise serializers.ValidationError("No se permiten direcciones IP privadas o reservadas.")
        return value

    def validate(self, attrs):
        if not self.instance and not attrs.get("secret"):
            raise serializers.ValidationError({"secret": "Este campo es obligatorio al crear el endpoint."})
        if self.instance and "secret" in attrs:
            raise serializers.ValidationError(
                {"secret": "La clave es inmutable; crea otro endpoint para rotarla."}
            )
        return attrs


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = (
            "id",
            "endpoint",
            "event",
            "target_url",
            "payload",
            "status",
            "attempts",
            "response_status",
            "response_body",
            "last_error",
            "created_at",
            "last_attempt_at",
            "delivered_at",
        )
        read_only_fields = fields
