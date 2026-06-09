# How SystemManager Works

## Arquitectura multi-tenant
- SystemManager usa `django-tenants` con esquema por tenant. El esquema `public` contiene la plataforma (tenants, dominios), y cada tenant tiene su propio esquema con datos empresariales (Business, FinancialEntry, ThirdParty, etc.).

## Flujos principales
- **Crear tenant:** Desde el panel de plataforma se crea un `Tenant` y un `Domain`. Se inicializan grupos por defecto y se crea una empresa y usuario administrador dentro del esquema del tenant.
- **Login:** El login valida si la petición llega desde un dominio tenant o desde la plataforma; usuarios staff pueden entrar al panel de plataforma.
- **Operaciones financieras:** Los movimientos (`FinancialEntry`) se crean dentro del esquema tenant y quedan registrados en `AuditEvent`.

## APIs para integraciones
- Se exponen endpoints JSON read-only para permitir integraciones rápidas: `financial-entries`, `third-parties`, `currency-rates`.
- Los endpoints admiten autenticación por sesión o JWT.
- Endpoint para obtener token: `/api/token/`
- Endpoint para renovar token: `/api/token/refresh/`

## Actualización de tasas (`CurrencyRate`)
- El proyecto ya está preparado para ejecutar la actualización automática de tasas con Celery y Redis.
- La tarea `businessmanagement.tasks.update_currency_rates` consulta la API definida en `CURRENCY_API_URL`, itera todos los tenants activos y crea/actualiza `CurrencyRate` para cada esquema.
- En caso de error, la tarea registra un `AuditEvent` indicándolo.

### Configuración recomendada con Docker Compose
- `compose.yml` ahora incluye los servicios `redis`, `celery_worker` y `celery_beat`.
- Usa estas variables en `.env`:

```
DB_HOST=db
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CURRENCY_API_URL=https://api.example.com/latest_rates
```

- Levanta el stack completo con:

```bash
docker compose -f compose.yml up --build -d
```

- El servicio `celery_beat` programa la tarea diaria y el `celery_worker` la ejecuta.

### Qué hace la tarea
1. `beat` lanza `update_currency_rates` según la programación en `config/celery.py`.
2. El worker evalúa cada tenant en `Tenant.objects.exclude(schema_name='public')`.
3. Dentro de `schema_context`, actualiza `CurrencyRate` y crea registros de auditoría.
4. Si falla un tenant, el proceso continúa con demás tenants.


## Recomendaciones operativas
- En producción usar PostgreSQL, Celery+Redis, y un reverse proxy (nginx) con HTTPS.
- Configurar backups regulares de la base de datos y rotación de logs.
- Añadir tests que cubran separación por tenant y permisos.

## Siguientes mejoras sugeridas
- Endpoints API autenticados con tokens (DRF + SimpleJWT) para integraciones M2M.
- Exportes a Excel/PDF y paginación en vistas (ya implementada en `financial_entry_list` y `audit_event_list`).
- Implementar job de actualización de tasas con Celery y monitorización.
