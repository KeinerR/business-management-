# Cierre de fase 5: interfaz y producción

Actualizado: 24 de octubre de 2026. Estado: implementación en validación; el despliegue HTTPS real sigue siendo un criterio de cierre.

## Preparación

1. Crear `.env.prod` desde `.env.prod.example`, sin versionarlo. Usar secretos únicos, dominios públicos/tenant reales y orígenes CSRF HTTPS. Incluir `127.0.0.1` en `DJANGO_ALLOWED_HOSTS` para el healthcheck interno. No usar `DJANGO_DEBUG=True`.
2. Ejecutar explícitamente `docker compose --env-file .env.prod -f compose.production.yml up --build -d`.
3. Configurar un proxy TLS confiable hacia `127.0.0.1:8000`. El puerto se limita a loopback por defecto. Para un proxy en otra red, ajustar `WEB_BIND_ADDRESS` y restringir el acceso al backend. El proxy debe conservar `Host` y sobrescribir `X-Forwarded-Proto` con el protocolo real; no confiar en encabezados suministrados por el cliente. Configurar certificado válido, DNS público/tenant y límite de carga compatible con documentos de 10 MB.
4. Provisionar tenant público, dominios y administradores mediante comandos/panel del proyecto. El healthcheck funciona sin tenant provisionado, pero las páginas del negocio requieren sus dominios. No ejecutar `create_demo_tenant` en producción: ese comando crea una cuenta con contraseña conocida.
5. Ejecutar `python scripts/staging_smoke.py https://plataforma.example https://tenant.example` desde un equipo autorizado. No desactivar la verificación TLS.

## Criterios de aceptación pendientes en staging

- [ ] HTTPS real: certificado, `ALLOWED_HOSTS`, CSRF, cookies seguras, HSTS y redirección HTTP→HTTPS.
- [ ] Dominio público y dos tenants: login/logout real, roles y aislamiento de datos.
- [ ] Estáticos servidos por WhiteNoise; sin dependencia de CDN para Bootstrap.
- [ ] Worker y Beat saludables: `docker compose --env-file .env.prod -f compose.production.yml exec celery_worker celery -A config inspect ping`. Comprobar ejecución de una tarea y programación en logs; un ping no valida el trabajo completo.
- [ ] Documento privado: carga, descarga autorizada y rechazo a otro tenant; persistencia después de recrear contenedores.
- [ ] API JWT y webhook HTTPS contra un receptor controlado: firma, trazabilidad y reintentos.
- [ ] Backup de PostgreSQL/media y restauración probada en una instancia separada antes de operar con datos reales.
- [ ] Revisión visual de tenant empresa, persona natural y plataforma a 360, 768 y 1440 px, con teclado y ambos temas.

## Verificación reproducible de interfaz

Instalar Playwright fuera del checkout o en un directorio temporal (`npm install --prefix /tmp/systemmanager-ui playwright`). Con Chromium disponible:

```bash
NODE_PATH=/tmp/systemmanager-ui/node_modules CHROMIUM_PATH=/usr/bin/chromium \
  SM_BASE_URL=http://127.0.0.1:5000 node scripts/ui_smoke.cjs
```

El script verifica Inicio/login en tres anchos, menú móvil, ausencia de errores JavaScript, persistencia de tema y desbordamiento de página. Una cookie de sesión tenant temporal mediante `SM_SESSION_COOKIE` habilita dashboard, facturas y movimientos; nunca guardar esa cookie en Git ni en documentación. No ejecuta ni sustituye una inspección visual humana ni todos los flujos de escritura.

## Cambios del cierre

- Salud independiente del enrutamiento tenant, conservando validación de host y HTTPS; consulta real `SELECT 1` y 503 ante indisponibilidad.
- Backend de producción limitado a loopback por defecto.
- CSS global servido como estático, Bootstrap 5.3.3 local con hashes SRI verificados, contraste de botones oscuros y paneles que permiten tablas desplazables.
- Tema compatible con componentes Bootstrap y almacenamiento local bloqueado.
- Pipeline CI para dependencias, migraciones, pruebas, estáticos e imagen Docker. Su ejecución en GitHub debe comprobarse después de subir los cambios.

No marcar fase 5 terminada hasta registrar evidencia de los criterios de staging. Las pruebas locales y un build no demuestran que un dominio productivo está correctamente configurado.

## Evidencia local de esta entrega

- 42/42 pruebas aprobadas en Python 3.12 del cloud y en Python 3.13 dentro de la imagen. En la suite de imagen se desactiva la redirección HTTPS global para los tests funcionales HTTP; los tests específicos de HTTPS la activan explícitamente.
- `makemigrations --check --dry-run`: sin cambios. `pip check` de la imagen: dependencias consistentes.
- Imagen ejecutada con usuario `app`, Gunicorn, `DEBUG=False`, WhiteNoise, cookies seguras y HSTS: páginas públicas/tenant, login, salud y estáticos responden correctamente; HTTP sin encabezado del proxy redirige con 301. Esto simula terminación TLS y **no valida un certificado ni proxy real**.
- Build de imagen local con wheels descargados mediante TLS verificado y un Dockerfile temporal que sustituye únicamente la instalación de red por `pip --no-index --find-links`. El builder Docker no pudo acceder al repositorio de paquetes mediante la red del cloud. El build estándar del Dockerfile se delega al CI y al staging; no se declara probado aquí.
- Playwright con Chromium del sistema valida Inicio/login, dashboard/facturas/movimientos tenant y dashboard/listado de tenants de plataforma en tres tamaños (21 combinaciones de página y viewport). Se incorporó menú plegable de tenant/plataforma, contraste oscuro y tablas desplazables. Las comprobaciones automatizadas no cubren todos los formularios ni equivalen a revisión visual completa.

Para la prueba interna de imagen, `SM_PROXY_TEST=1` agrega `X-Forwarded-Proto: https` al navegador. Úsalo solo contra el backend local de prueba, nunca como sustituto del smoke test HTTPS externo. `SM_PLATFORM=1` selecciona páginas de plataforma y requiere una sesión de superadmin temporal. `SM_SCREENSHOT_DIR` permite guardar capturas fuera del repositorio.
