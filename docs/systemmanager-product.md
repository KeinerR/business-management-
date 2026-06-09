# SystemManager — Resumen de Producto

## Visión
SystemManager es una plataforma SaaS multi-tenant pensada para centralizar la gestión financiera y operativa de múltiples empresas (MiPyMEs y grupos de compañías). Ofrece aislamiento por tenant, control de accesos, auditoría completa y módulos financieros básicos con extensión para integrar inventarios y automatizaciones.

## Objetivos principales
- Proveer un panel de plataforma (Master) para gestionar tenants, dominios y usuarios.
- Proveer paneles por tenant para gestionar empleados, terceros, movimientos financieros y tasas de cambio.
- Mantener aislamiento estricto de datos entre tenants y trazabilidad mediante logs de auditoría.

## Funcionalidades ya implementadas (estado actual)
- **Autenticación:** Login por usuario (con validación por tenant y control para administradores de plataforma).
- **Multi-tenant:** Separación por esquemas (django-tenants) con creación de tenants y dominios desde el panel de plataforma.
- **Gestión de usuarios y empleados:** Creación de empleados ligados a un usuario, asignación de grupos/roles básicos.
- **RBAC básico:** Grupos por defecto: Administrador de empresa, Operador financiero, Solo lectura.
- **Movimientos financieros:** CRUD básico de `FinancialEntry` con tipo, estado, moneda y reportes sencillos.
- **Terceros (ThirdParty):** Gestión de clientes/proveedores.
- **Tasas de cambio:** Registro manual de `CurrencyRate` y listado en dashboard.
- **Auditoría:** `AuditEvent` para registrar acciones como creación de tenants, usuarios, movimientos.

## Problema detectado y corrección aplicada
- **Error:** `TypeError: 'Manager' object is not subscriptable` al cargar `dashboard`.
- **Causa:** Uso directo de `CurrencyRate.objects[:3]` — `objects` es un `Manager`, no un `QuerySet` subscriptable.
- **Fix aplicado:** Reemplazado por `CurrencyRate.objects.order_by('-rate_date', 'currency')[:3]` en `dashboard_view`.

Archivo modificado: [businessmanagement/views.py](businessmanagement/views.py#L146)

## Recomendaciones de mejora (priorizadas)
1. **Actualización automática de tasas:** Integrar un job periódico (Celery/cron + API externa) para poblar `CurrencyRate` automáticamente.
2. **Paginación y filtros:** Añadir paginación en listados largos (`financial_entries`, `audit_events`) y filtros por fechas/usuario/tenant.
3. **Interfaz de cambio de tenant:** Mejor experiencia para usuarios con acceso a múltiples tenants (switch sin relogin y control de sesiones).
4. **Permisos finos:** Implementar permisos basados en objetos (Django guardian o políticas personalizadas) para acciones sensibles en `FinancialEntry` y `ThirdParty`.
5. **APIs REST:** Exponer endpoints REST (Django REST Framework) para integraciones y clientes SPA/mobile.
6. **Export/Import:** Exportar reportes a Excel/PDF y permitir la importación masiva de terceros/movimientos CV/CSV.
7. **Tests y CI:** Añadir tests unitarios/integración (especial foco en separación por tenant) y pipeline de CI que ejecute las migraciones y pruebas.

## Propuesta de roadmap inmediato (sprint 1)
- Implementar actualización automática de `CurrencyRate` (con configuración por tenant).
- Añadir paginación y filtros básicos para `financial_entry_list` y `audit_event_list`.
- Añadir endpoints REST read-only para listados principales.

## Arquitectura y decisiones técnicas
- **Base de datos:** Multi-schema (django-tenants) sobre PostgreSQL (recomendado para producción).
- **Colas y tareas periódicas:** Celery + Redis (o cron simple para MVP) para tareas asíncronas y actualizaciones de tasas.
- **Seguridad:** HTTPS obligatorio; contraseñas hashed (Django por defecto), roles de plataforma y tenant separados.

## Cómo contribuir / desplegar localmente (breve)
1. Crear entorno virtual e instalar dependencias: `pip install -r requirements.txt`.
2. Configurar base de datos PostgreSQL y variables de entorno (DB, SECRET_KEY, ALLOWED_HOSTS).
3. Ejecutar migraciones: `python manage.py migrate_schemas` (o el comando correspondiente para django-tenants).
4. Cargar datos de ejemplo o crear tenant desde panel de plataforma.

## Próximos pasos (sugeridos)
- Revisar prioridades y confirmar si quiere que implemente la actualización automática de tasas y la paginación ahora.
- Generar una lista de endpoints REST prioritarios (e.g., `GET /api/tenants/`, `GET /api/financial-entries/`).

---
Documento generado y organizado a partir de `systemmanager-product-brief.md`.
