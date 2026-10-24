# SystemManager — Resumen de producto

Plataforma SaaS multi-tenant para gestión financiera y operativa de empresas y personas naturales, con datos separados por esquemas PostgreSQL.

## Capacidades implementadas

- Plataforma: tenants, dominios, administradores y seguimiento/suspensión del servicio.
- Operación: usuarios, roles, empleados, terceros, proyectos y categorías.
- Finanzas: movimientos, pagos parciales/multimoneda, cartera, conciliación bancaria CSV/XLSX.
- Comercial: cotizaciones, facturas PDF, notas crédito/débito y reglas tributarias/retenciones.
- Control: auditoría, aprobaciones, notificaciones internas, plan contable y presupuestos/forecast.
- Herramientas: documentos privados versionados, importaciones con preview/rollback y API de escritura/webhooks.

## Madurez y siguientes pasos

Fases 1–4 entregadas según el alcance registrado; fase 5 (UX y producción) en validación. La referencia detallada es [ESTADO_IMPLEMENTACION.md](ESTADO_IMPLEMENTACION.md); el cierre requiere [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

Se implementaron automatización de tasas USD/EUR, forecast con pagos en otra moneda y PDF de nota débito. Falta verificar la conexión real al proveedor de tasas después de aplicar acceso de red. OCR, notificaciones externas y partida doble requieren alcance posterior. Las pruebas locales no certifican cumplimiento fiscal ni despliegue productivo.

La auditoría de junio se conserva como diagnóstico histórico, no como lista vigente de funcionalidades faltantes.
