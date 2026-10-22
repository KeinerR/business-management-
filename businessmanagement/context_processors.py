from .modules import AVAILABLE_MODULES, MODULE_GROUPS

def sidebar_modules_processor(request):
    """
    Provee la variable 'grouped_modules' a todas las plantillas,
    filtrando por lo que el tenant actual tiene habilitado.
    """
    tenant = getattr(request, "tenant", None)
    # Solo procesar si estamos en un contexto de tenant y el usuario está autenticado
    if not tenant or not request.user.is_authenticated:
        return {}

    enabled_modules_list = getattr(tenant, "enabled_modules", [])
    module_labels = dict(AVAILABLE_MODULES)
    
    # Mapeo de iconos y nombres de URL para la navegación
    MODULE_META = {
        # Resumen
        "cartera": {"icon": "bi-pie-chart", "url": "cartera_dashboard"},
        
        # Gestión Financiera
        "finances": {"icon": "bi-cash-stack", "url": "financial_entry_list"},
        "categories": {"icon": "bi-tags", "url": "financial_category_list"},
        "banking": {"icon": "bi-bank", "url": "bank_account_list"},
        "currency_rates": {"icon": "bi-currency-exchange", "url": "currency_rate_list"},
        "budget": {"icon": "bi-calculator", "url": "budget_list"},
        
        # Comercial y Ventas
        "invoices": {"icon": "bi-file-earmark-text", "url": "invoice_list"},
        "quotes": {"icon": "bi-chat-quote", "url": "quote_list"},
        "credit_notes": {"icon": "bi-file-earmark-minus", "url": "credit_note_list"},
        "debit_notes": {"icon": "bi-file-earmark-plus", "url": "debit_note_list"},
        "taxes": {"icon": "bi-percent", "url": "tax_rule_list"},
        
        # Operaciones y CRM
        "third_parties": {"icon": "bi-people", "url": "third_party_list"},
        "projects": {"icon": "bi-briefcase", "url": "project_list"},
        "employees": {"icon": "bi-person-badge", "url": "employee_list"},
        
        # Banca y Pagos
        "payments": {"icon": "bi-credit-card", "url": "payment_list"},
        "bank_statements": {"icon": "bi-file-earmark-ruled", "url": "bank_statement_list"},
        "reconciliations": {"icon": "bi-check2-square", "url": "reconciliation_list"},  # Redirige a cuentas bancarias
        
        # Herramientas
        "import_batch": {"icon": "bi-upload", "url": "generic_import_batch_list"},
        "audit": {"icon": "bi-clock-history", "url": "audit_event_list"},
        
        # Accesos
        "users": {"icon": "bi-person", "url": "tenant_user_list"},
        "groups": {"icon": "bi-shield", "url": "tenant_group_list"},
    }

    grouped_modules = {}
    for group_name, mods in MODULE_GROUPS.items():
        items = []
        for m_name in mods:
            if m_name in enabled_modules_list:
                meta = MODULE_META.get(m_name, {"icon": "bi-circle", "url": "#"})
                items.append({
                    'name': m_name,
                    'label': module_labels.get(m_name, m_name),
                    'icon': meta['icon'],
                    'url_name': meta['url']
                })
        if items:
            grouped_modules[group_name] = items

    return {"grouped_modules": grouped_modules}
