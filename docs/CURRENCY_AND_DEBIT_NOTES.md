# Forecast multimoneda, tasas automáticas y PDF de notas débito

Entrega: 24 de octubre de 2026. No requiere migraciones ni nuevas dependencias.

## Conversión y forecast

`services/currency.py` centraliza la conversión usada por pagos, cartera, conciliación y forecast. COP vale 1 como moneda base: no necesita una fila `CurrencyRate`. Cada pago se convierte a la moneda del movimiento usando las tasas de su **fecha exacta de pago**. No se toma la tasa actual ni una fecha posterior para modificar el saldo histórico.

Los saldos se agrupan por mes y moneda, sin sumar monedas distintas. Los sobrepagos no generan saldos negativos. Si falta una tasa válida, el movimiento completo se excluye de los importes de ese bucket y se muestra “Proyección incompleta” con el movimiento y la tasa faltante. Otros movimientos válidos siguen calculándose; las cifras de ese bucket son parciales hasta registrar la tasa.

## Actualización de tasas

- Fuente pública sin clave: `https://open.er-api.com/v6/latest/USD` (ExchangeRate-API). Es una tasa de referencia, no una certificación de TRM fiscal ni una cotización de Binance P2P.
- Se consulta una vez por ejecución. Con base USD, USD/COP se toma directamente; EUR/COP se calcula como COP por USD dividido por EUR por USD. Se almacena la fecha de actualización del proveedor (UTC), no se inventa una fecha de cotización.
- Se rechazan redirecciones, payloads incompletos, base distinta de USD, valores no positivos/no finitos, fechas futuras y datos de más de tres días. Se conserva la verificación TLS y un timeout de conexión/lectura.
- Se replica atómicamente en cada tenant activo, excluyendo `public`. Si falla uno, se continúa con los demás y la tarea termina con error visible para señalar actualización parcial. Un fallo del proveedor no modifica datos.
- Los registros manuales existentes conservan prioridad. Reejecutar no duplica tasas ni auditorías sin cambios. Editar una tasa automática desde la UI la marca `manual` para protegerla de próximas actualizaciones.
- `BINANCE` permanece manual; USD y Binance P2P no se consideran equivalentes.
- Beat programa `businessmanagement.tasks.update_currency_rates` diariamente a las **03:00 America/Bogota**. `CURRENCY_AUTO_UPDATE=False` deshabilita esa programación al reiniciar Beat; la ejecución manual sigue disponible.
- Ejecución manual: `python manage.py update_currency_rates`. Se auditan las escrituras por tenant y los errores se registran en logs. La tarea no rellena históricos: las fechas anteriores que falten se registran manualmente.
- Atribución visible en la pantalla de tasas con enlace a ExchangeRate-API. Revisar los términos del proveedor antes de publicar una integración comercial.

### Estado de conectividad del cloud

La consulta real devolvió 403 del proxy por dominio no permitido. Se guardó `open.er-api.com` en el borrador de acceso de red, conservando los presets existentes. Guardar el borrador no aplica ni publica el cambio. Revisar/guardar la configuración del entorno y publicarla; después ejecutar el comando manual y confirmar tasas/auditoría antes de considerar verificada la integración externa. No requiere proporcionar una clave.

## Notas de débito

- Listado y detalle tenant con enlaces de descarga: `/debit-notes/` y `/debit-notes/<id>/`.
- PDF autenticado y condicionado al módulo `debit_notes`: `/debit-notes/<id>/pdf/`. Documento inexistente devuelve 404.
- Incluye empresa, tercero opcional, factura asociada opcional, fecha, estado, moneda, ítems, subtotal, impuestos, retenciones, total y observaciones.
- Usa los totales guardados del documento; no recalcula impuestos con reglas que podrían haber cambiado después de la emisión.
- Escapa caracteres de marcado, ajusta textos y repite encabezados de tabla cuando hay varias páginas; registra el acceso en auditoría.
- Se añadieron las plantillas de listado/detalle que faltaban. Los formularios ausentes de creación/edición de notas son deuda preexistente y no forman parte de esta descarga de documentos existentes.

## Evidencia

53 pruebas aprobadas tanto en Python 3.12 del cloud como en Python 3.13 de la imagen: conversiones COP y cruzadas, fecha de cada pago, forecast incompleto, idempotencia, preservación manual, fallos de proveedor/tenant y respuesta/acceso PDF. Se generó además un PDF y se extrajo su texto con `pdftotext`: subtotal 100, impuesto 19, retención 2, total 117; caracteres `<`, `>` y `&` conservados correctamente. Las respuestas del proveedor en la suite son controladas: no sustituyen la validación del acceso externo pendiente.
