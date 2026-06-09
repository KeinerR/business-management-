# AUDITORÍA COMPLETA — BUSINESS MANAGEMENT (SystemManager)
**Fecha:** Junio 2026 · **Stack:** Django 5.1 + django-tenants 3.7 + PostgreSQL + Celery/Redis + Bootstrap 5 (SSR) · **Verificación runtime:** ✅ `manage.py check` OK, migraciones OK, servidor arranca, schema público y tenant responden 200.

---

# 1. FUNCIONALIDADES EXISTENTES

## 1.1 Ya implementadas (✅ completas y funcionales)

| Módulo | Detalle |
|---|---|
| Multi-tenancy | django-tenants, schema por tenant, tipos `business`/`individual`, dominio por tenant |
| Panel plataforma | CRUD de tenants + bootstrap automático (empresa, admin, grupos, dominio) |
| Roles y permisos | Grupos: Administrador de empresa / Operador financiero / Solo lectura + decorador `tenant_group_required` |
| Empleados / Usuarios / Grupos | CRUD completo con vinculación User↔Employee |
| Terceros (CRM) | Clientes/Proveedores/Ambos, activar/inactivar |
| Proyectos | Tipos (empresa/cliente/personal), estados |
| Categorías financieras | Ingreso/Egreso/Transferencia |
| Movimientos financieros | income/expense/AR/AP, estados pending/partial/paid/cancelled, filtros, export CSV, adjuntos, flag `personal` |
| Pagos | Pagos parciales por movimiento, conversión multi-moneda por fecha, recálculo de estado |
| Tasas de cambio | CRUD + tarea Celery diaria (`update_currency_rates`) |
| Facturación | Invoice + InvoiceItem, IVA %, PDF (reportlab), CRUD |
| Cotizaciones | Quote + QuoteItem, flujo Draft→Accepted→Converted (crea Invoice + FinancialEntry AR, idempotente) |
| Cartera (AR/AP) | Dashboard con overdue, próximos vencimientos, panel por tercero, saldo restante con conversión |
| Auditoría | AuditEvent en la mayoría de operaciones de escritura |
| API JSON | 3 endpoints read-only + JWT (simplejwt) |
| Módulos por tenant | `enabled_modules` (JSON) + decorador `module_enabled_required` |

## 1.2 Parcialmente implementadas (⚠️ requieren completarse — NO recrear)

| Módulo solicitado | Estado real | Qué falta |
|---|---|---|
| **1. Banking/Conciliación** | Modelos completos (BankAccount, BankStatement, BankTransaction, Reconciliation) + import CSV + sugerencias + confirmación | Import **Excel**, **match manual** (elegir pago/movimiento), **conciliación masiva**, listado/detalle de extractos, manejo de `direction` (campo existe pero siempre vacío), edición de cuentas bancarias |
| **2. Cartera AR/AP** | Dashboard funcional por tercero | Aging buckets (0-30/31-60/61-90/+90), **riesgo de cartera**, vista por **proyecto** y por **factura**, alertas activas (hoy es solo visual), export |
| **4. Cotizaciones** | Flujo completo Quote→Accept→Invoice con conversión automática | **Editar cotización**, PDF, fecha de expiración/vencimiento automático, numeración correcta (hoy genera prefijo `REC-` igual que factura — bug) |
| **5. Motor tributario** | Solo `tax_percentage` plano en Invoice/Quote | Reglas configurables por tenant: IVA múltiple, **retenciones**, exenciones, impuesto por ítem |
| **10. Notificaciones** | Inexistente como sistema; solo `django.contrib.messages` (flash) | Modelo Notification in-app + generación automática (vencimientos, eventos) |
| **11. Importación masiva** | Solo CSV bancario (sin preview ni rollback) | Pipeline genérico CSV/Excel con **preview, validación previa y rollback** |
| **12. API/Webhooks** | 3 endpoints GET read-only | API de escritura (DRF serializers/viewsets) y **webhooks** por eventos |

## 1.3 Faltantes (❌ no existen)

- **3. Notas Crédito/Débito** (CreditNote/DebitNote) — no hay rastro
- **6. Forecast financiero** (presupuestos, flujo de caja proyectado, variaciones)
- **7. Plan contable** (Chart of Accounts)
- **8. Gestión documental** (solo existe `FinancialEntry.attachment` simple; sin versionado/OCR/trazabilidad)
- **9. Workflow de aprobaciones** (estados Draft/Pending/Approved/Rejected con bitácora)
- Notificaciones Email/WhatsApp/SMS (acordado: solo **In-App** por ahora)
- Auto-marcado de facturas vencidas (`Invoice.OVERDUE` existe como choice pero **nada lo asigna jamás**)

---

# 2. PROBLEMAS ENCONTRADOS

## 2.1 Bugs CRÍTICOS (P0)

| # | Bug | Ubicación | Impacto |
|---|---|---|---|
| B1 | **Vistas financieras SIN autenticación**: `payment_list`, `cartera_dashboard`, `project_list` no tienen `@login_required` ni `@tenant_required` | views.py L1890, L2143, L2363 | Cualquier anónimo ve pagos, cartera y proyectos del tenant. **Fuga de datos financieros** |
| B2 | **~560 líneas de código duplicado**: `_normalize_text`, `_parse_csv_date`, `_compute_payment_match_score`, `bank_statement_import_csv`, `bank_transaction_suggestions`, `reconciliation_confirm` están definidas DOS veces (L2511-2773 y L2776-3073). Python usa silenciosamente la segunda definición | views.py | Código muerto, riesgo de editar la copia equivocada, divergencia garantizada |
| B3 | `_parse_csv_date` llama `date.strptime(...)` que **no existe** (es `datetime.strptime`). El except lo silencia → todas las filas con fecha `DD/MM/YYYY` se **descartan sin avisar** en el import bancario | views.py L2524/L2789 | Pérdida silenciosa de transacciones importadas |
| B4 | `payment_create` ejecuta `_convert_amount` **fuera de try** al renderizar el GET → **error 500** si el pago tiene moneda distinta y no hay tasa para esa fecha | views.py L2225-2230 | Pantalla de pago inaccesible |
| B5 | `invoice_edit` ejecuta `invoice.items.all().delete()` **ANTES** del bloque `transaction.atomic()` → si la edición falla, los ítems originales **se pierden** | views.py L1364 | Pérdida de datos de facturas |
| B6 | `Quote.save()` genera número con prefijo `REC-` (copy-paste de Invoice) → cotizaciones y facturas comparten patrón de numeración | tenantdata/models.py L553 | Confusión documental/contable |
| B7 | `Reconciliation` tiene `UniqueConstraint(bank_transaction, status)` pero `get_or_create` incluye payment+financial_entry → si en una re-visita el mejor candidato cambia, se intenta crear una 2ª PROPOSED → **IntegrityError 500** | models + views | Conciliación rompe al re-procesar |
| B8 | **Bootstrap dev roto**: `ensure_dev_tenants` crea tenant `demo` con `enabled_modules=[]` y `create_demo_tenant` NO repara módulos en tenants existentes → el tenant demo del compose queda **con todos los módulos bloqueados** (verificado en runtime) | management commands + compose.yml | Demo inutilizable tras `docker compose up` |
| B9 | Vistas de Facturas y Cotizaciones **no aplican** `module_enabled_required("invoices")` → bypass por URL directa aunque el módulo esté deshabilitado (el sidebar solo lo oculta) | views.py | El sistema de módulos no se respeta |

## 2.2 Riesgos de seguridad

- **Credenciales superuser hardcodeadas en `compose.yml`** (usuario, email y contraseña en texto plano, committeadas a git).
- `.env` committeado con `DJANGO_DEBUG=True` y `SECRET_KEY` débil — sin separación dev/prod.
- `invoice_delete` permite **borrado físico** de facturas incluso pagadas/emitidas (sin restricción de estado) — riesgo de integridad contable; la auditoría no preserva el contenido borrado.
- `financial_entry_edit` permite poner status=PAID sin generar `Payment` (inconsistente con la regla aplicada en `financial_entry_create`).
- API DRF sin throttling ni scoping fino (cualquier usuario autenticado del tenant lee todo).

## 2.3 Deuda técnica

- **0 tests** (`tests.py` tiene 3 líneas vacías) — ninguna de las 8 fases de testing existe.
- N+1 / queries ineficientes:
  - Admin de Tenants: 2 cambios de schema **por fila** del listado (`tenant_business_name` + `tenant_admin_user`).
  - `cartera_dashboard`: cálculo de saldos en Python fila por fila (no agregación SQL); aceptable hoy, no escala.
  - `update_currency_rates`: llama a la API externa **una vez por tenant** (mismo payload) en vez de 1 vez global.
- `Invoice.OVERDUE` nunca asignado (falta tarea Celery).
- `payment_list` corta `entry_choices[:50]` arbitrariamente sin búsqueda.
- `LANGUAGE_CODE='en-us'` y `TIME_ZONE='UTC'` con UI 100% español y datos de Colombia.
- `BankTransaction.direction` campo declarado pero nunca poblado ni usado.
- Variables muertas: `total_paid_local`, `paid_sum` en `payment_create`.
- Archivos basura en repo: `celerybeat-schedule*` (3 archivos binarios), `Pasted image.png` (163KB).

## 2.4 Docker

| Problema | Detalle |
|---|---|
| `runserver` como CMD de producción | Dockerfile usa el dev server de Django; falta gunicorn |
| Sin `STATIC_ROOT` ni `collectstatic` | `collectstatic` fallaría; sin whitenoise para servir estáticos |
| Sin `.dockerignore` | La imagen copia `.git`, `media/`, `celerybeat-schedule`, `.env` |
| Secretos en compose | Superuser hardcodeado (ver 2.2) |
| Race condition | `celery_worker`/`celery_beat` arrancan en paralelo con `web` que ejecuta `migrate_schemas` → workers pueden arrancar contra DB sin migrar |
| Sin healthcheck en `web` | Solo la DB tiene healthcheck |
| Postgres 17 sin versión pineada de respaldo en prod | OK para dev |

---

# 3. REDUNDANCIAS DETECTADAS

| Redundancia | Acción propuesta |
|---|---|
| **Modelos `Business` y `Employee` duplicados** en `businessmanagement` (schema público) y `tenantdata` (tenant). Los del público son legacy: ninguna vista/form/admin los usa | **Eliminar** (migración de borrado; sin datos en uso) |
| 6 funciones duplicadas en views.py (~560 líneas) | **Eliminar** la primera copia; extraer a `services/banking.py` |
| Lógica de procesamiento de ítems repetida 3 veces (invoice_create, invoice_edit, quote_create) + `calculate_totals`/`save()` casi idénticos en Quote/Invoice | **Fusionar** en servicio único `services/documents.py` |
| Gating de módulos duplicado e inconsistente: template sidebar + decoradores + `AVAILABLE_MODULES` (forms) ≠ choices del admin (al admin le falta `currency_rates`) | **Centralizar** registro de módulos en un solo lugar (`modules.py`) |
| `CurrencyRate` duplicada por tenant siendo dato global + fetch API por tenant | Mantener modelo (compatibilidad) pero fetch 1 vez y replicar |
| `views.py` monolítico (3.131 líneas) | Dividir por dominio (finanzas, facturación, banca, plataforma) |
| TODO.md describe tareas ya implementadas | Limpiar/archivar |

---

# 4. MAPEO FUNCIONAL

## 4.1 Flujo Persona Natural
`Registro (solo vía panel plataforma) → módulos: finances, projects, third_parties, categories → ingresos/gastos (flag personal auto) → pagos → cartera`

- ✅ Funciona: registro de ingresos/gastos, flag personal automático, formularios simplificados.
- ⚠️ Fricción: debe pasar por plataforma para crear su cuenta (no hay self-signup — decisión de diseño aceptable); dashboard muestra KPIs empresariales (empleados/usuarios) irrelevantes para persona natural; sin presupuesto personal ni metas; "Cartera AR/AP" usa jerga empresarial.
- ❌ Falta: forecast personal (presupuesto mensual), notificaciones de vencimiento.

## 4.2 Flujo Empresa
`Registro → config → terceros → cotización → factura → cartera → pagos → conciliación → reportes`

- ✅ Funciona: flujo comercial completo Quote→Invoice→FinancialEntry(AR)→Payments→Reconciliation. Es el corazón del sistema y está bien encadenado.
- ⚠️ Cuellos de botella: no se puede editar cotización (hay que cancelar y recrear); registrar pago requiere navegar Finanzas→fila→pagos (3+ clics, sin acceso directo desde factura); factura no muestra sus pagos; sin numeración secuencial fiscal; reportes = solo export CSV plano.
- ❌ Falta: notas crédito/débito (sin forma de ajustar una factura emitida), retenciones (crítico para Colombia), aprobaciones de gasto, alertas de vencimiento activas.

---

# 5. AUDITORÍA UX/UI

- **Navegación**: sidebar plano de hasta 16 enlaces sin agrupación visual fuerte; sin breadcrumbs; "Pagos" y "Banco" desconectados de las facturas que los originan.
- **Dashboard**: solo tarjetas numéricas; **sin gráficos** (no hay librería de charts); KPIs iguales para empresa y persona natural.
- **Dark mode**: ❌ inexistente.
- **Responsive**: grid colapsa bien en móvil, pero tablas anchas sin `table-responsive` en varias vistas.
- **Accesibilidad**: falta `aria-*` en acciones, contraste OK, foco OK (Bootstrap).
- **Consistencia**: estilos inline en `base.html` (no hay archivo estático CSS propio); botones mezclan variantes (`btn-info` re-tematizado vía CSS hack).
- **Productividad**: sin acciones rápidas (registrar pago desde factura/cartera), sin búsqueda global, estados vacíos sin CTA.

---

# 6. VALIDACIÓN DE CALIDAD (Formularios)

- ✅ Backend: montos > 0 validados (FinancialEntry, Payment); dominio único; passwords coinciden; campos condicionales por tipo de tenant.
- ⚠️ Inconsistencias:
  - `InvoiceForm`/`QuoteForm` no validan `due_date >= issue_date`.
  - Ítems de factura llegan por `request.POST.getlist` sin formset → sin validación estructurada, errores genéricos ("Error al crear factura: ..." expone str(e) interno).
  - `tax_percentage` admite negativos.
  - Import CSV no reporta filas descartadas (combinado con B3 = pérdida silenciosa).
  - `PaymentForm` no valida sobre-pago en el form (solo en la vista, y con bug B4).
  - Sin sanitización extra necesaria (Django templates auto-escape ✅, ORM parametrizado ✅, CSRF ✅).

---

# 7. PROPUESTA DE ARQUITECTURA Y PLAN DE IMPLEMENTACIÓN

> Principio: **no crear nada duplicado**. Banking, Cartera, Cotizaciones, Pagos ya existen → se completan y refactorizan. Solo se crean los módulos realmente faltantes, todos multi-tenant, integrados a `enabled_modules` + `AuditEvent` + permisos existentes + Docker.

### FASE A — Refactor y fixes críticos (P0, prerequisito de todo)
1. Eliminar las 6 funciones duplicadas; dividir `views.py` en módulos por dominio.
2. Proteger `payment_list`, `cartera_dashboard`, `project_list` (B1) y aplicar `module_enabled_required` a facturas/cotizaciones (B9).
3. Corregir B3 (fechas CSV), B4 (500 en pagos), B5 (atomic en invoice_edit), B6 (prefijo `QUO-`), B7 (constraint conciliación), B8 (enabled_modules en demo).
4. Centralizar registro de módulos (`modules.py`) usado por forms, admin, decoradores y sidebar; nuevos módulos: `banking`, `quotes`, `taxes`, `budget`, `documents`, `approvals`, `notifications`.
5. Eliminar modelos legacy `businessmanagement.Business/Employee` + limpiar archivos basura del repo.
6. Tarea Celery: auto-marcar `Invoice.OVERDUE`.
7. Suite de tests base (pytest-django): modelos, servicios, flujo quote→invoice→payment, permisos.

### FASE B — Completar módulos parciales (P1)
8. **Banking**: import Excel (openpyxl), listado/detalle de extractos, match manual, conciliación masiva, `direction` poblado.
9. **Cartera**: aging buckets, riesgo por tercero, vista por proyecto/factura, alertas → alimenta Notificaciones.
10. **Cotizaciones**: editar, PDF, expiración automática, numeración secuencial por tenant (`QUO-0001`, `FAC-0001`).
11. **Facturación**: panel de pagos dentro de la factura ("Registrar pago" en 1 clic), bloqueo de borrado físico de facturas emitidas/pagadas (→ anulación).

### FASE C — Módulos nuevos núcleo (P1)
12. **Notas Crédito/Débito**: `CreditNote`/`DebitNote` ligadas a Invoice, generan FinancialEntry de ajuste, PDF, numeración propia.
13. **Motor tributario**: `TaxRule` por tenant (IVA múltiple, ReteFuente/ReteIVA/ReteICA, exenciones) aplicado a Quote/Invoice; reemplaza al `tax_percentage` plano manteniendo compatibilidad.
14. **Notificaciones In-App**: modelo `Notification` + campana en navbar + generación por Celery (vencimientos cartera, facturas overdue) y por eventos (pago recibido, cotización aceptada).
15. **Workflow de aprobaciones**: motor genérico (`ApprovalRequest` + bitácora) con estados draft/pending/approved/rejected; aplicado primero a Cotizaciones y Gastos.

### FASE D — Módulos escalables (P2)
16. **Plan contable**: `Account` jerárquico (clase/grupo/cuenta/subcuenta, plantilla PUC Colombia) + mapeo desde categorías — estructura preparatoria, sin partida doble aún.
17. **Forecast**: `Budget`/`BudgetLine` por proyecto/categoría + flujo de caja proyectado (cartera + recurrencias) + comparativo presupuesto vs real.
18. **Gestión documental**: `Document` con GenericFK, versionado y trazabilidad (OCR diferido a fase posterior).
19. **Importación masiva genérica**: pipeline CSV/Excel con preview → validación → commit → rollback (`ImportBatch`), reutilizado por terceros, movimientos y banco.
20. **API + Webhooks**: DRF ViewSets de escritura + `WebhookEndpoint`/`WebhookDelivery` con dispatch Celery para invoice.created, invoice.paid, payment.registered, financial_entry.created.

### FASE E — UX/UI y Docker (transversal)
21. Rediseño: dashboard con gráficos (Chart.js), dashboard diferenciado persona natural vs empresa, sidebar agrupado, breadcrumbs, dark mode, acciones rápidas, estados vacíos.
22. Docker prod: gunicorn + whitenoise + `STATIC_ROOT` + `.dockerignore` + secretos por env + healthchecks + orden de arranque correcto.

### Qué fusionar / eliminar
- **Fusionar**: lógica de ítems Quote/Invoice (+futuras notas) en un servicio; gating de módulos centralizado.
- **Eliminar**: modelos legacy públicos, funciones duplicadas, archivos basura, variables muertas.
- **NO se elimina** ningún modelo con datos de usuario; todas las migraciones son aditivas y compatibles con datos existentes.

---

# 8. ORDEN DE EJECUCIÓN RECOMENDADO

| Iteración | Contenido | Justificación |
|---|---|---|
| **1** | Fase A completa (fixes P0 + refactor + tests base) | Sin esto, todo lo nuevo hereda los bugs |
| **2** | Fase B (Banking/Cartera/Quotes completados) + Notas C/D + auto-overdue | Mayor valor de negocio inmediato; cierra el ciclo de facturación |
| **3** | Motor tributario + Notificaciones in-app + Aprobaciones | Cumplimiento fiscal + control interno |
| **4** | Plan contable + Forecast + Documental + Import masivo + Webhooks + UX/Docker prod | Escalabilidad |
