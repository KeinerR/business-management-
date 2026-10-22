"""
Registro centralizado de módulos disponibles en SystemManager.
Este archivo es la fuente de verdad para formularios, vistas y decoradores.
"""

AVAILABLE_MODULES = (
    ("finances", "Finanzas (Movimientos)"),
    ("projects", "Proyectos"),
    ("third_parties", "Terceros (CRM)"),
    ("categories", "Categorías Financieras"),
    ("invoices", "Facturación y Ventas"),
    ("quotes", "Cotizaciones"),
    ("employees", "Gestión de Empleados"),
    ("currency_rates", "Tasas de Cambio"),
    ("credit_notes", "Notas de Crédito"),
    ("debit_notes", "Notas de Débito"),
    ("taxes", "Configuración de Impuestos (Motor Tributario)"),
    ("banking", "Cuentas Bancarias"),
    ("bank_statements", "Extractos Bancarios"),
    ("reconciliations", "Conciliación"),
    ("budget", "Presupuestos"),
    ("cartera", "Cartera (AR/AP)"),
    ("payments", "Pagos"),
    ("import_batch", "Importación Masiva"),
    ("audit", "Auditoría"),
    ("users", "Usuarios"),
    ("groups", "Grupos y Roles"),
)

# Módulos recomendados por defecto para personas naturales
MODULES_INDIVIDUAL = [
    "finances", 
    "projects", 
    "third_parties", 
    "categories",
    "payments",
    "cartera",
]

# Módulos adicionales/exclusivos recomendados para empresas
MODULES_BUSINESS = [
    "invoices", 
    "quotes",
    "employees", 
    "currency_rates", 
    "credit_notes", 
    "debit_notes", 
    "taxes", 
    "banking",
    "bank_statements",
    "reconciliations",
    "budget",
    "import_batch",
    "audit",
    "users",
    "groups",
]

# Categorías de módulos para visualización agrupada en Dashboard y Sidebar
MODULE_GROUPS = {
    "Resumen": ["cartera"],
    "Gestión Financiera": ["finances", "categories", "banking", "currency_rates", "budget"],
    "Comercial y Ventas": ["invoices", "quotes", "credit_notes", "debit_notes", "taxes"],
    "Operaciones y CRM": ["third_parties", "projects", "employees"],
    "Banca y Pagos": ["payments", "bank_statements", "reconciliations"],
    "Herramientas": ["import_batch", "audit"],
    "Accesos": ["users", "groups"],
}
