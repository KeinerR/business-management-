# TODO - Pagos / Reconciliación (Payment)

## Auditoría / P0 (estado)
- [x] B1: Gating + autenticación aplicada a vistas financieras (payment_list/cartera_dashboard/project_list)
- [x] B5: invoice_edit borra items dentro de atomic()
- [x] B4: payment_create GET/remaining envuelto para evitar 500 por conversión faltante
- [x] B9: module_enabled_required aplicado a facturas/cotizaciones
- [x] Hotfix: `celery_worker` ya inicia (NameError DebitNote)
- [x] B2: eliminar segunda copia duplicada en `businessmanagement/views.py` (560 líneas)
- [x] B3: asegurar `_parse_csv_date` sin descartes silenciosos y con logging (agregar conteo/report)
- [x] B6: prefijo QUO- para Quote (tenantdata/models.py)
- [x] B7: ajustar reconciliación para no romper por UniqueConstraint al re-procesar (update en vez de crear)
- [ ] B8: ensure_dev_tenants/create_demo_tenant reparan enabled_modules correctamente (ver comandos)


## Paso 1


- [x] Investigar repo: no existe módulo Payment/pagos/reconciliación.
- [x] Confirmar estado actual: `FinancialEntry.status` ya tiene pending/partial/paid/cancelled.
- [x] Confirmar relación: `Invoice.financial_entry` (OneToOne).

## Paso 2 (preparación)

- [x] Corregir `TemplateSyntaxError` en `businessmanagement/template/tenant/invoice_form.html`.

## Paso 3 (implementación módulo Payment)

- [x] Agregar modelo `Payment` en `tenantdata/models.py` (FK a `FinancialEntry`, auditoría).
- [x] Agregar migración de DB.

- [x] Agregar `PaymentForm` en `businessmanagement/forms.py`.
- [x] Agregar vistas para pantalla directa de Pagos indexada por `FinancialEntry` (listado + crear).

- [ ] Agregar lógica de conversión de moneda (usando `CurrencyRate`) para reconciliación.
- [ ] Actualizar `FinancialEntry.status` tras crear pago.
- [ ] Agregar rutas en `businessmanagement/urls.py`.
- [ ] Crear templates:
  - [ ] list/ index pagos por movimiento (FinancialEntry)
  - [ ] formulario de pago
- [ ] Registrar en `businessmanagement/admin.py`.

## Paso 4 (verificación)

- [ ] Ejecutar migraciones y correr checks/compilación.
- [ ] Validar flujo: registrar pagos parciales y que el estado del `FinancialEntry` cambie correctamente.

# TODO - Workflow comercial: Cotizaciones → Facturas → Pagos

## Paso 5 (descubrimiento / diseño)

- [x] Confirmar que `Invoice`/`InvoiceItem`/`Payment` existen.
- [x] Definir la regla: al “convertir” una cotización aceptada se crea `Invoice` + `InvoiceItem`.
- [x] Confirmar adicional (según tu respuesta): al convertir a Factura también se crea `FinancialEntry` como `ACCOUNT_RECEIVABLE` para que aparezca en `cartera_dashboard` y se puedan registrar pagos.

## Paso 6 (modelos y migraciones)

- [x] Agregar modelos `Quote`, `QuoteItem` en `tenantdata/models.py`.
- [x] Implementar campos y lógica básica (status, totales, calculate_totals).
- [x] Crear migración para Quote/QuoteItem.

## Paso 7 (forms)

- [ ] Agregar `QuoteForm` y UI de items (mismo patrón que `InvoiceForm`).
- [ ] Agregar `QuoteItem` form si se usa (si no, manejar items por POST arrays).

## Paso 8 (vistas + URLs)

- [x] Crear `quote_list`, `quote_create`, `quote_detail`.
- [x] Crear endpoint `quote_accept` (cambia status a accepted).
- [x] Crear endpoint `quote_convert_to_invoice` (accepted → crea Invoice, InvoiceItems, FinancialEntry).
- [x] Agregar rutas en `businessmanagement/urls.py`.

## Paso 9 (templates)

- [ ] Crear `quote_list.html`.
- [ ] Crear `quote_form.html` (clonando `invoice_form.html`).
- [ ] Crear `quote_detail.html` (incluye acciones Aceptar/Convertir según status).
- [ ] Ajustar navegación si existe menú (opcional).

## Paso 10 (verificación funcional)

- [ ] Probar: cotización draft → aceptar → convertir → aparece Invoice en invoice_list.
- [ ] Probar: aparece `FinancialEntry` con `ACCOUNT_RECEIVABLE` en `cartera_dashboard`.
- [ ] Probar: registrar pago(s) y que `FinancialEntry.status` evoluciona pending/partial/paid correctamente.
- [ ] Validar que no hay duplicados al convertir (con bloqueo por status/relación).
