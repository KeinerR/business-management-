# Estado de implementación y continuidad

**Actualizado:** 24 de octubre de 2026
**Fuente de verdad para continuar el desarrollo:** este documento.
**Roadmap de origen:** `AUDITORIA_COMPLETA_2026-06.md`.

## Estado general

| Fase | Alcance | Estado |
|---|---|---|
| 1 | Estabilización, seguridad, módulos, multi-tenant y pruebas base | ✅ Terminada |
| 2 | Banking, cartera, cotizaciones y facturación | ✅ Terminada |
| 3 | Notas C/D, motor tributario, notificaciones y aprobaciones | ✅ Terminada |
| 4 | Módulos escalables (5 bloques) | ✅ Terminada |
| 5 | UX/UI global y Docker para producción | 🟡 En curso |

**Punto actual:** Fase 5, primera entrega de UX/UI y despliegue preparada.
**Siguiente trabajo:** ejecutar los criterios de staging en [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md). La implementación local avanzó; no se declara cerrada la fase sin validar HTTPS real.

## Fases terminadas

### Fase 1 — Estabilización

- Protección de vistas y control de módulos por tenant.
- Correcciones críticas de facturas, pagos, numeración y conciliación.
- Configuración regional, tareas Celery y pruebas de regresión.
- Registro centralizado de módulos en `businessmanagement/modules.py`.

### Fase 2 — Ciclo financiero/comercial

- Banking: CSV/XLSX, detalle de extractos, conciliación manual y masiva.
- Cartera: aging, riesgo, moneda, vistas por proyecto/factura y exportación.
- Cotizaciones: edición, PDF, expiración y conversión idempotente.
- Facturas: borrador/emisión/anulación, cuentas por cobrar y pagos relacionados.

### Fase 3 — Control empresarial

- Notas crédito y débito.
- Reglas tributarias por tenant, impuestos y retenciones.
- Notificaciones internas con deduplicación.
- Aprobaciones de cotizaciones y gastos con trazabilidad.

## Fase 4 — Módulos escalables

| Bloque | Módulo | Estado | Resultado |
|---|---|---|---|
| 1/5 | Plan contable | ✅ Terminado | Cuentas jerárquicas, PUC inicial idempotente y mapeo de categorías |
| 2/5 | Presupuestos y forecast | ✅ Terminado | Budget/BudgetLine, ejecución real, variación y flujo AR/AP proyectado |
| 3/5 | Gestión documental | ✅ Terminado | Repositorio privado, versiones inmutables, trazabilidad, archivado lógico y descarga autenticada |
| 4/5 | Importación masiva genérica | ✅ Terminado | CSV/XLSX, preview, validación, confirmación atómica, rollback y lector compartido con banca |
| 5/5 | API de escritura y webhooks | ✅ Terminado | ViewSets tenant-aware, permisos, idempotencia y entregas HMAC en Celery con reintentos |

### Gestión documental — alcance entregado

- Modelos tenant `Document` y `DocumentVersion`.
- Numeración secuencial de versiones protegida con transacción y bloqueo de fila.
- Conservación del nombre original, MIME, tamaño, responsable, fecha y notas.
- Archivos con nombre físico opaco y descarga únicamente desde una vista autenticada.
- Validación de extensiones y límite de 10 MB.
- Listado con búsqueda/filtros, detalle, nueva versión y archivo/reactivación.
- Eventos de auditoría para creación, nuevas versiones y cambios de estado.
- OCR queda expresamente diferido; no forma parte de este bloque.

### Importación masiva — alcance entregado

- Pipeline centralizado en `businessmanagement/services/imports.py` sin recrear `ImportBatch` ni `ImportedRecord`.
- Lectura segura de CSV/XLSX, encabezados normalizados, máximo de 10 MB y 5.000 filas.
- Preview con validaciones por fila antes de escribir información empresarial.
- Importación de terceros y movimientos financieros; relaciones verificadas dentro del tenant.
- Confirmación atómica e idempotencia por estado del lote.
- Rollback administrativo trazable, bloqueado cuando los registros ya tienen operaciones relacionadas.
- El importador bancario reutiliza el lector genérico; conserva su flujo especializado de extractos y conciliación.
- UI tenant para carga, preview, historial, detalle y reversión; módulo `import_batch` aplicado correctamente.

### API de escritura y webhooks — alcance entregado

- API DRF v1 en `/api/v1/` para consultar, crear y actualizar movimientos financieros y terceros; se mantienen las rutas GET antiguas para compatibilidad.
- Escrituras limitadas a los roles Administrador de empresa y Operador financiero, con contexto tenant obligatorio y verificación de módulos para Finanzas y Terceros.
- `Idempotency-Key` obligatorio en POST, con huella del cuerpo y replay de respuestas; reutilizar una clave con otro cuerpo responde 409.
- Endpoints webhook administrables por API, secretos no expuestos ni editables, destinos HTTPS públicos y sin redirecciones.
- Eventos emitidos: `invoice.created`, `invoice.paid`, `payment.registered` y `financial_entry.created`.
- Entregas persistidas y consultables por API, firmadas con HMAC-SHA256; reintentos Celery para errores de red, HTTP 429 y HTTP 5xx.
- `WebhookDelivery` conserva payload, destino, intentos, resultado HTTP y último error para trazabilidad.

## Fase 5 — avances

- Navegación tenant agrupada por dominio, filtrada por módulos habilitados y con indicador de sección activa.
- Breadcrumbs, enlace para saltar al contenido, control accesible de tema claro/oscuro y soporte responsive del panel lateral.
- Landing pública comercial con explicación de funcionalidades y públicos, llamadas a iniciar sesión e ilustración conceptual sin métricas ni operaciones de clientes; se añadieron pruebas para impedir la reaparición de datos de muestra.
- Navegación desde Inicio dirigida al dashboard tenant o de plataforma según el contexto y los permisos; los usuarios autenticados en el dominio público no reciben enlaces que los envíen al dashboard tenant.
- Dashboard diferenciado para persona natural y empresa, acciones rápidas condicionadas a módulos y comparativo accesible de ingresos/egresos mensuales en COP.
- Imagen Docker ejecutada como usuario sin privilegios, `.dockerignore`, Gunicorn, almacenamiento estático WhiteNoise configurable y endpoint `/health/` que verifica la base de datos.
- Nuevo `compose.production.yml` con healthchecks, dependencias ordenadas, volúmenes persistentes y ejecución de migraciones/estáticos al iniciar. El despliegue debe estar detrás de un proxy TLS.
- Se eliminó el usuario/contraseña predefinido del arranque de desarrollo; las cuentas se crean interactivamente.
- La advertencia de `requests` se resolvió fijando `chardet` a una versión compatible.
- `docker-compose.yml` se conserva por compatibilidad como configuración heredada; el README distingue explícitamente los comandos de desarrollo (`compose.yml`) y producción (`compose.production.yml`).
- El panel de plataforma incluye cartera de clientes con búsqueda, filtros de estado y renovación, paginación, ficha de seguimiento por tenant, contacto administrativo, resumen de uso, administradores, dominios y actividad reciente.
- Se añadieron campos internos de plan, estado de servicio, fecha de renovación y notas de seguimiento; solo se muestran en las vistas protegidas de superadmin. La ficha permite suspender/reactivar el acceso con POST y el middleware bloquea el acceso al tenant suspendido, manteniendo disponible la página de salud.

## Validación acumulada

- Checks: `docker compose -f compose.yml run --rm --no-deps web python manage.py check`.
- Suite actual: **53 pruebas**, todas aprobadas con `docker compose -f compose.yml run --rm --no-deps web python manage.py test businessmanagement`.
- Verificar migraciones: `docker compose -f compose.yml run --rm --no-deps web python manage.py makemigrations --check --dry-run`.
- Última migración del bloque documental: `tenantdata/0014_document_documentversion_and_more.py`.
- Última migración del bloque de importaciones: `tenantdata/0015_importbatch_confirmed_at_importbatch_rolled_back_at_and_more.py`.
- Migración API/webhooks `0016_webhookendpoint_webhookdelivery_apiidempotencyrecord.py` aplicada en los esquemas existentes; `showmigrations tenantdata` confirma todas las migraciones en estado aplicado.
- Migración de seguimiento de clientes `businessmanagement/0009_tenant_service_tracking.py` aplicada al schema compartido.
- `compose.production.yml` validado y `collectstatic` completado (154 archivos copiados, 444 postprocesados).
- `pip check` sin dependencias rotas; `requests 2.32.3`, `urllib3 2.8.0` y `chardet 5.2.0` cargan sin la advertencia anterior.
- Smoke test autenticado en tenant demo: `/documents/` y `/documents/create/` responden HTTP 200; módulo `documents` habilitado en demo.
- Smoke test de importación: preview HTTP 200, confirmación, detalle HTTP 200, rollback y listado HTTP 200; lote de prueba quedó revertido.

## Instrucciones para la siguiente IA

1. Leer este archivo y `AUDITORIA_COMPLETA_2026-06.md`.
2. Revisar `git status` y preservar cambios existentes; los archivos runtime de Celery versionados no deben confundirse con código funcional.
3. El bloque de importaciones está terminado; no recrear `ImportBatch`/`ImportedRecord` ni duplicar el lector CSV/XLSX.
4. La API de escritura y webhooks está implementada y la migración 0016 está aplicada en los esquemas existentes; probar endpoints con JWT en un tenant habilitado antes de publicar integraciones externas.
5. La primera entrega de Fase 5 está en el árbol; no iniciar el stack de producción sin crear `.env.prod` desde `.env.prod.example` y configurar un proxy TLS real.
6. Completar la revisión de interfaz en viewport móvil y validar healthcheck, static files, login y tareas Celery en un entorno de staging.
7. Al terminar la fase, actualizar la tabla y el “Punto actual” de este documento.

## Entrega de cierre de fase 5 — 24 de octubre

- Healthcheck antes del enrutamiento tenant: responde sin tenant público provisionado, valida `ALLOWED_HOSTS`, mantiene redirección HTTPS y ejecuta `SELECT 1` para detectar fallos reales de consulta.
- Puerto de producción en loopback por defecto; ejemplo de hosts incluye la IP del healthcheck interno.
- CSS global extraído a estáticos y Bootstrap 5.3.3 servido localmente con integridad SRI verificada; se elimina la descarga de fuentes de Google.
- Tema sincronizado con Bootstrap, tolerancia a bloqueo de localStorage, contraste oscuro y contención de tablas en paneles móviles.
- Smoke test Playwright reproducible: Inicio/login, dashboard tenant, facturas y movimientos en 360/768/1440 px; persistencia de tema y ausencia de desbordamiento horizontal. También se verificaron dashboard y listado de tenants de plataforma en los tres tamaños.
- Suite ampliada a 42 pruebas, incluyendo salud sin tenant, host inválido, HTTPS y fallo de base de datos.
- Añadidos pipeline CI, smoke test HTTPS de solo lectura y guía de aceptación de staging. CI remoto aún no ejecutado.

### Alcance pendiente fuera de fase 5

Los pendientes de forecast multimoneda, tasas automáticas y PDF de nota débito se implementaron en la entrega siguiente (ver abajo). OCR, canales externos de notificación y partida doble siguen fuera del alcance entregado. No interpretar la tabla de fases como cobertura de cada aspiración del roadmap original.

## Entrega funcional posterior a fase 5

- Conversión compartida con COP como base y fecha exacta por pago; forecast multimoneda con avisos ante tasas faltantes.
- Sincronización diaria de tasas de referencia USD/EUR por Celery, preservando tasas manuales y aislamiento por tenant. Falta confirmar consulta externa después de aplicar acceso a `open.er-api.com`; no se declara validada en vivo.
- PDF de nota débito y plantillas de listado/detalle con descarga autenticada y auditoría.
- Suite vigente: 53 pruebas aprobadas. No hay cambios de modelos ni migraciones nuevas.
- Operación, límites y evidencia: [CURRENCY_AND_DEBIT_NOTES.md](CURRENCY_AND_DEBIT_NOTES.md).

## Mejora visual de interfaces

Sistema visual compartido en `static/businessmanagement/design.css`: navegación lateral, tarjetas, formularios, tablas, landing y login; estados activos de plataforma, iconos SVG locales y temas claro/oscuro. Validación: 53 pruebas y comprobaciones de navegador en 360/768/1440 px para páginas públicas, tenant y plataforma. No equivale a una auditoría exhaustiva de todos los formularios ni cierra la validación HTTPS pendiente.
