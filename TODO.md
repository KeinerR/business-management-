# TODO - Pagos / Reconciliación (Payment)

## Paso 1

- [x] Investigar repo: no existe módulo Payment/pagos/reconciliación.
- [x] Confirmar estado actual: `FinancialEntry.status` ya tiene pending/partial/paid/cancelled.
- [x] Confirmar relación: `Invoice.financial_entry` (OneToOne).

## Paso 2 (preparación)

- [x] Corregir `TemplateSyntaxError` en `businessmanagement/template/tenant/invoice_form.html`.

## Paso 3 (implementación módulo Payment)

- [ ] Agregar modelo `Payment` en `tenantdata/models.py` (FK a `FinancialEntry`, auditoría).
- [x] Agregar migración de DB.

- [ ] Agregar `PaymentForm` en `businessmanagement/forms.py`.
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

- [ ] Agregar modelos `Quote`, `QuoteItem` en `tenantdata/models.py`.
- [ ] Implementar campos y lógica básica (status, totales, calculate_totals).
- [ ] Crear migración para Quote/QuoteItem.

## Paso 7 (forms)

- [ ] Agregar `QuoteForm` y UI de items (mismo patrón que `InvoiceForm`).
- [ ] Agregar `QuoteItem` form si se usa (si no, manejar items por POST arrays).

## Paso 8 (vistas + URLs)

- [ ] Crear `quote_list`, `quote_create`, `quote_detail`.
- [ ] Crear endpoint `quote_accept` (cambia status a accepted).
- [ ] Crear endpoint `quote_convert_to_invoice` (accepted → crea Invoice, InvoiceItems, FinancialEntry).
- [ ] Agregar rutas en `businessmanagement/urls.py`.

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
