# SystemManager

SystemManager es una aplicación Django multi-tenant para la gestión financiera y operativa de pequeñas y medianas empresas.

Qué hace esta aplicación y por qué es útil
-----------------------------------------
- Gestiona varias empresas separadas por tenant, con cada empresa en su propio esquema.
- Permite administrar la estructura interna de la empresa: empleados, usuarios y roles.
- Registra terceros como clientes y proveedores, y controla si están activos.
- Lleva movimientos financieros básicos: ingresos, egresos, cuentas por cobrar y cuentas por pagar.
- Permite crear, editar y generar facturas con ítems y descargar PDF.
- Ofrece auditoría de acciones clave para saber quién hizo qué.
- Incluye tasas de cambio para manejar diferentes monedas.

Utilidad práctica hoy
---------------------
- Para una pyme, es una base para centralizar datos administrativos y financieros.
- Permite reemplazar hojas de cálculo aisladas con registros estructurados.
- Ayuda a controlar el flujo de caja y los pendientes de pago/ cobro.
- Facilita la emisión y gestión de facturas dentro de la misma plataforma.

Cómo se puede extender
----------------------
- Se puede adaptar para gestionar proyectos: cada proyecto puede agrupar ingresos y gastos, y permitir seguimiento mensual e histórico por proyecto.
- También se puede usar para gastos personales: una persona natural puede registrar sus ingresos y egresos personales dentro de un proyecto o categoría específica.
- Esta estructura es una base natural para agregar: reportes mensuales, presupuestos por proyecto, dashboards de avance y alertas de vencimiento.

Resumen rápido:
- Multi-tenant (django-tenants) con panel de plataforma y panel por tenant.
- Gestión de empleados, terceros, movimientos financieros, tasas de cambio y auditoría.

Quickstart (local):
1. Crear y activar un entorno virtual.
2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Configurar PostgreSQL y variables de entorno (`DJANGO_SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DJANGO_ALLOWED_HOSTS`).
4. Ejecutar migraciones (incluyendo esquemas tenants):

```bash
python manage.py migrate
# Para django-tenants puede requerir comandos adicionales como migrate_schemas
```

5. Crear un superusuario y ejecutar el servidor:

```bash
python manage.py createsuperuser
python manage.py runserver
```

### Comando de prueba
Puedes crear un tenant completo de prueba con datos iniciales usando:

```bash
python manage.py create_demo_tenant
```

Opciones útiles:

```bash
python manage.py create_demo_tenant --schema=demo --domain=demo.127.0.0.1.nip.io --name="Demo Tenant"
```

APIs básicas (JSON):
- `/api/financial-entries/` (GET)
- `/api/third-parties/` (GET)
- `/api/currency-rates/` (GET)
- `/api/token/` (POST) para obtener JWT tokens
- `/api/token/refresh/` (POST) para renovar access token

La API acepta autenticación por sesión o por JWT.

Para detalles y documentación de funcionamiento, ver `docs/HOW_SYSTEM_WORKS.md`.
Para ejemplos de uso de la API y JWT, ver `README_API.md`.
Celery + Redis (tareas periódicas)
---------------------------------
El archivo `compose.yml` es el entorno de desarrollo. No crea usuarios con contraseñas predeterminadas; crea la cuenta administrativa de forma interactiva:

```bash
docker compose -f compose.yml exec web python manage.py createsuperuser
```

### Despliegue con Docker

La configuración de producción está separada en `compose.production.yml`. Requiere un proxy inverso con TLS, una clave Django y credenciales de base de datos fuertes. No montes el código fuente ni el archivo `.env` dentro del contenedor.

1. Crea tu archivo local de variables a partir del ejemplo y reemplaza todos los valores de muestra por secretos únicos:

```bash
cp .env.prod.example .env.prod
```

2. Construye y levanta el stack de producción:

```bash
docker compose --env-file .env.prod -f compose.production.yml up --build -d
```

El stack inicia PostgreSQL, Redis, Gunicorn con WhiteNoise, un worker y Celery Beat. Las migraciones tenant y la recolección de estáticos se ejecutan antes de iniciar Gunicorn. Los archivos subidos, los datos de PostgreSQL, Redis y el calendario de Celery Beat se guardan en volúmenes Docker.

3. Crea la cuenta administradora inicial en el esquema público:

```bash
docker compose --env-file .env.prod -f compose.production.yml exec web python manage.py createsuperuser
```

4. Verifica la disponibilidad y los logs:

```bash
docker compose --env-file .env.prod -f compose.production.yml ps
docker compose --env-file .env.prod -f compose.production.yml logs -f web
```

El endpoint interno `/health/` verifica conectividad con la base de datos. Si terminas TLS en un proxy, configura `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` para los dominios reales y conserva el envío del encabezado `X-Forwarded-Proto: https`.

El archivo `docker-compose.yml` es una configuración heredada; usa explícitamente `compose.yml` para desarrollo o `compose.production.yml` para producción.

### Logs de Celery en desarrollo

```bash
docker compose -f compose.yml logs -f celery_worker
```

Las tareas programadas activas están definidas en `config/celery.py`.
