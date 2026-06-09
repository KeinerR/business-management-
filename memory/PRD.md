# PRD — Business Management (SystemManager)

## Problem statement original
Auditoría completa e implementación de nuevos módulos para plataforma Business Management multi-tenant (Django 5.1 + django-tenants + PostgreSQL + Celery/Redis + Bootstrap 5 SSR, ejecutada vía Docker). 9 fases: auditoría profunda, mapeo funcional, detección de redundancias, validación de calidad, UX, nuevos módulos (12 candidatos), refactorización, testing, entregable de informe ANTES de implementar.

## Decisiones del usuario (junio 2026)
- Código ya cargado en el entorno (/app, proyecto Django existente).
- Prioridad de módulos: decidida por el agente según hallazgos de auditoría.
- Notificaciones: SOLO In-App (sin SendGrid/Twilio por ahora).
- Flujo: informe primero → esperar aprobación → implementar.

## Arquitectura actual
- SHARED app: `businessmanagement` (Tenant, Domain, vistas, forms, templates en businessmanagement/template/)
- TENANT app: `tenantdata` (Business, Employee, ThirdParty, Project, FinancialCategory, CurrencyRate, FinancialEntry, AuditEvent, Invoice/Item, Payment, Quote/Item, BankAccount, BankStatement, BankTransaction, Reconciliation)
- config/: settings (django-tenants), celery (beat: update_currency_rates diaria)
- Docker: compose.yml (db postgres17, web:5000, redis, celery_worker, celery_beat)
- Entorno local de auditoría: PostgreSQL 15 + Redis instalados localmente (service postgresql/redis-server start), DB sprinty/sprinty/complexpassword123; correr con DB_HOST=localhost. Tenants: public, demo (modules vacíos - BUG B8), demo2 (business, todos los módulos, user demo_admin/demo1234).

## Hecho (2026-06)
- [x] FASE AUDITORÍA completa → informe en /app/docs/AUDITORIA_COMPLETA_2026-06.md
- [x] Verificación runtime: check OK, migrate_schemas OK, server arranca, tenant demo2 creado.

## Hallazgos clave (resumen — detalle en el informe)
- Bugs P0: B1 vistas sin auth (payment_list/cartera_dashboard/project_list), B2 ~560 líneas duplicadas en views.py (6 funciones x2), B3 date.strptime inexistente (CSV), B4 500 en payment_create GET, B5 delete items fuera de atomic en invoice_edit, B6 prefijo REC- en Quote, B7 IntegrityError conciliación, B8 enabled_modules vacío en demo, B9 facturas/cotizaciones sin module gating.
- Redundancias: modelos legacy Business/Employee en businessmanagement, lógica items duplicada x3, gating módulos descentralizado.
- 0 tests. Docker prod inseguro (runserver, secretos en compose, sin collectstatic).

## Backlog priorizado (pendiente de APROBACIÓN del usuario)
- P0 (Iteración 1 - Fase A): fixes B1-B9, refactor views.py por dominio, modules.py central, eliminar legacy, tarea auto-OVERDUE, tests base.
- P1 (Iteración 2 - Fase B+C parcial): completar Banking (Excel, match manual, masivo), Cartera (aging, riesgo), Quotes (edit, PDF, numeración), Notas Crédito/Débito, pagos desde factura.
- P1 (Iteración 3): Motor tributario (TaxRule: IVA, retenciones), Notificaciones In-App, Workflow aprobaciones.
- P2 (Iteración 4): Plan contable (PUC), Forecast/Budget, Gestión documental, Import masivo genérico, Webhooks+API escritura, rediseño UX (charts, dark mode, dashboards diferenciados), Docker prod.

## Próxima acción
Esperar aprobación del usuario sobre el plan → comenzar Iteración 1 (Fase A).
