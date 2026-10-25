# Pendientes vigentes

Referencia: `docs/ESTADO_IMPLEMENTACION.md`. El antiguo checklist de pagos/cotizaciones describía trabajo ya implementado y fue sustituido para evitar duplicaciones.

## Prioridad actual: cierre de fase 5

- [ ] Completar criterios de staging HTTPS de `docs/PRODUCTION_READINESS.md`.
- [ ] Revisión visual completa de plataforma, persona natural y empresa.
- [ ] Ejecutar y confirmar el nuevo pipeline en GitHub después de subir cambios.

## Siguiente ciclo funcional

- [x] Forecast: descontar pagos de otra moneda mediante conversión consistente.
- [x] Implementar actualización automática de tasas con proveedor y política definidos.
- [ ] Validar consulta real a `open.er-api.com` después de aplicar el permiso de red guardado en el borrador.
- [x] PDF de notas débito.
- [x] Validar la matriz de habilitación/bloqueo de los 25 módulos, menú, rutas directas, API y roles tenant; validar además el bloqueo de escritura para Solo lectura.
- [ ] Completar pruebas de aislamiento cross-tenant y concurrencia; la cobertura de permisos/módulos ya añadida no reemplaza esas pruebas.

## Deuda técnica

- [ ] Completar las plantillas preexistentes ausentes para creación/edición de notas crédito/débito; listado/detalle de débito ya funcionan.

- [ ] Separar `views.py` por dominio y consolidar lógica documental repetida.
- [ ] Revisar uso y migración de modelos legacy públicos Business/Employee antes de eliminarlos.
- [ ] Retirar archivos runtime versionados sin perder datos necesarios.
- [ ] Revisar borrado ORM de usuarios en el esquema público: al limpiar un usuario temporal, Django intentó consultar relaciones de `tenantdata_employee`, inexistentes en public. La sesión temporal fue revocada y la cuenta desactivada; no se cambió el modelo en esta entrega.

## Fuera del alcance actual

OCR, notificaciones email/WhatsApp/SMS y contabilidad por partida doble.
