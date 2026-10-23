from django.conf import settings
from django.shortcuts import render


class TenantServiceAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        tenant_schema = getattr(tenant, "schema_name", settings.PUBLIC_SCHEMA_NAME)
        static_url = getattr(settings, "STATIC_URL", "/static/")
        if (
            tenant_schema != settings.PUBLIC_SCHEMA_NAME
            and not tenant.is_active
            and request.path_info != "/health/"
            and not request.path_info.startswith(static_url)
        ):
            return render(
                request,
                "guest/service_suspended.html",
                status=403,
            )
        return self.get_response(request)
