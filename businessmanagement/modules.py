"""
Registro centralizado de módulos disponibles en SystemManager.
Este archivo es la fuente de verdad para formularios, vistas y decoradores.
"""

AVAILABLE_MODULES = (
    ("finances", "Finanzas (Movimientos)"),
    ("projects", "Proyectos"),
    ("third_parties", "Terceros (CRM)"),
    ("categories", "Categorías Financieras"),
    ("invoices", "Facturación y Cotizaciones"),
    ("employees", "Gestión de Empleados"),
    ("currency_rates", "Tasas de Cambio"),
    ("credit_notes", "Notas de Crédito"),
    ("debit_notes", "Notas de Débito"),
    ("taxes", "Configuración de Impuestos (Motor Tributario)"),
    ("banking", "Conciliación Bancaria"),
    ("budget", "Presupuestos"),
)

# Módulos recomendados por defecto para personas naturales
MODULES_INDIVIDUAL = ["finances", "projects", "third_parties", "categories"]

# Módulos adicionales/exclusivos recomendados para empresas
MODULES_BUSINESS = ["invoices", "employees", "currency_rates", "credit_notes", "debit_notes", "taxes", "banking"]

# Categorías de módulos para visualización agrupada en Dashboard y Sidebar
MODULE_GROUPS = {
    "Gestión Financiera": ["finances", "categories", "banking", "currency_rates", "budget"],
    "Comercial y Facturación": ["invoices", "quotes", "credit_notes", "debit_notes", "taxes"],
    "Operaciones y CRM": ["third_parties", "projects", "employees"],
}