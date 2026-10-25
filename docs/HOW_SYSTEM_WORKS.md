# Cómo funciona SystemManager

Estado vigente: [ESTADO_IMPLEMENTACION.md](ESTADO_IMPLEMENTACION.md). Despliegue: [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

## Arquitectura y flujos

Django 5.1 con PostgreSQL y django-tenants: `public` contiene plataforma, tenants y dominios; cada tenant tiene esquema propio para usuarios, empresa y operaciones. Los roles principales son Administrador de empresa, Operador financiero y Solo lectura. Los módulos se habilitan por tenant.

El panel de plataforma provisiona tenants, dominios y administradores y controla estado de servicio. El flujo comercial es cotización → aceptación → factura/cuenta por cobrar → pagos → conciliación. También existen impuestos/retenciones, notas crédito/débito, aprobaciones, notificaciones internas, presupuestos, plan contable, documentos versionados e importaciones CSV/XLSX.

## API y tareas

Se conservan endpoints GET históricos y hay API de escritura `/api/v1/` con autenticación sesión/JWT, permisos por rol/módulo e idempotencia. Consultar `README_API.md` para recursos y webhooks HMAC con entregas Celery.

Celery usa Redis. Beat programa vencimiento de facturas y cotizaciones. `update_currency_rates` descarga tasas de referencia USD/EUR desde ExchangeRate-API y las replica por tenant activo sin sobrescribir tasas manuales. Beat la programa a las 03:00 America/Bogota; se puede desactivar con `CURRENCY_AUTO_UPDATE=False`. El cloud requiere aplicar el permiso de red a `open.er-api.com` antes de verificar la consulta real. Ver [tasas y notas débito](CURRENCY_AND_DEBIT_NOTES.md).

## Desarrollo y producción

En desarrollo usar explícitamente `compose.yml`; en producción `compose.production.yml`, variables privadas y proxy HTTPS. El Dockerfile ejecuta Gunicorn sin privilegios y WhiteNoise sirve estáticos cuando se habilita. El endpoint `/health/` comprueba una consulta de base de datos sin necesitar un tenant previamente registrado.

El comando `create_demo_tenant` crea un usuario con contraseña conocida y solo debe usarse en demos aisladas; el entorno cloud preparado no lo ejecuta. La configuración de desarrollo usa `ensure_dev_tenants` para preparar dominios y módulos sin crear ese usuario.

La matriz de permisos tenant cubre los 25 módulos, el menú, las rutas, las APIs y los roles; los 58 tests de `BusinessFlowTests` pasaron en la última validación, junto con pruebas focalizadas de solo lectura. Aún faltan pruebas exhaustivas de aislamiento entre tenants y concurrencia, staging HTTPS, restauración de backups e integraciones HTTPS reales. Ver la guía de aceptación antes de operar con datos reales.
