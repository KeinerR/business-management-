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

3. Configurar PostgreSQL y variables de entorno (`SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`).
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
Para ejecutar la tarea periódica que actualiza `CurrencyRate` se recomienda usar Redis como broker y Celery.

1. Construir la imagen y levantar servicios con Docker Compose:

```bash
docker compose -f compose.yml up --build -d
```

Esto crea cuatro servicios: `db`, `redis`, `web`, `celery_worker` y `celery_beat`.

2. Configurar variables de entorno (en `.env`):

```
DJANGO_SECRET_KEY=...
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=db
DB_PORT=5432
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CURRENCY_API_URL=https://api.example.com/latest_rates
```

3. Verificar el estado de los contenedores:

```bash
docker compose -f compose.yml ps
```

4. Para ver logs de Celery:

```bash
docker compose -f compose.yml logs -f celery_worker
```

La tarea `businessmanagement.tasks.update_currency_rates` está configurada para ejecutarse diariamente a las 03:00 UTC por defecto. Ajusta `config/celery.py` si necesitas otro horario.
