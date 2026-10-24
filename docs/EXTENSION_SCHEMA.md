# Esquema de extensión para gestión por proyectos y gastos personales

> Propuesta histórica: Project, FinancialCategory, vínculos financieros, tipos de tenant y presupuestos ya están implementados. No recrear estos modelos. Consultar ESTADO_IMPLEMENTACION.md para el alcance vigente; subproyectos y clasificación automática siguen siendo posibles extensiones.

Este documento propone una evolución de la app `SystemManager` para que no solo gestione la empresa, sino también:

- Gastos e ingresos por proyecto.
- Seguimiento mensual de finanzas.
- Uso personal / persona natural para gastos personales.

## Objetivo

Crear una estructura que permita:

1. Registrar y agrupar entradas financieras en proyectos.
2. Filtrar y reportar por mes o por proyecto.
3. Mantener la lógica de multi-tenant y roles actuales.
4. Permitir que un "tenant" pueda representar una empresa o una persona natural.

## Modelo propuesto

### `Project`

Representa un proyecto de la empresa, un cliente, un área interna o un perfil personal.

Campos:
- `business` : ForeignKey(`Business`) — el negocio/tenant dueño del proyecto.
- `name` : CharField(max_length=255)
- `description` : TextField(blank=True)
- `project_type` : CharField(choices=[
    - `company` -> Proyecto interno de empresa,
    - `client` -> Proyecto para cliente / obra,
    - `personal` -> Proyecto de gastos personales,
    - `other` -> Otro,
  ])
- `start_date` : DateField(null=True, blank=True)
- `end_date` : DateField(null=True, blank=True)
- `status` : CharField(choices=[`active`, `completed`, `archived`], default=`active`)
- `third_party` : ForeignKey(`ThirdParty`, null=True, blank=True) — cliente o proveedor asociado.
- `owner` : ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True) — responsable del proyecto o persona natural.
- `created_at`, `updated_at`

### `FinancialCategory`

Permite clasificar entradas para análisis más claros.

Campos:
- `business` : ForeignKey(`Business`)
- `name` : CharField(max_length=120)
- `category_type` : CharField(choices=[`income`, `expense`, `transfer`])
- `is_active` : BooleanField(default=True)
- `created_at`, `updated_at`

### `FinancialEntry` (extensión)

Añadir campos:
- `project` : ForeignKey(`Project`, null=True, blank=True)
- `category` : ForeignKey(`FinancialCategory`, null=True, blank=True)
- `personal` : BooleanField(default=False) [opcional]

Uso:
- Para seguimiento mensual basta `entry_date` + filtros por rango.
- Para seguimiento por proyecto, se filtra por `project`.
- Para uso personal, los registros pueden agruparse en proyectos de tipo `personal`.

### `Invoice` (extensión opcional)

Añadir campo:
- `project` : ForeignKey(`Project`, null=True, blank=True)

Esto permite facturar un proyecto específico y relacionar la factura con su proyecto.

## Relaciones principales

- `Business` 1:N `Project`
- `Business` 1:N `FinancialCategory`
- `Business` 1:N `FinancialEntry`
- `Project` 1:N `FinancialEntry`
- `Project` 1:N `Invoice`
- `ThirdParty` puede ser cliente/proveedor de `Project` y de `FinancialEntry`

## Cómo apoyar el uso mensual y por proyecto

### Seguimiento mensual

No se necesita un campo nuevo si se usa `entry_date`.

- Filtros existentes: `date_from`, `date_to`, `period`
- Añadir opción de `period=monthly` o `period=project` en las vistas.
- Reportes simples: total por mes, totales por tipo de entrada.

### Seguimiento por proyecto

- Crear pantalla de proyectos.
- En `financial_entries` permitir filtrar por `project`.
- En `invoices` permitir filtrar por `project`.
- Mostrar resumen por proyecto:
  - ingresos totales
  - gastos totales
  - saldo
  - avance vs presupuesto si se añade más adelante.

## Uso como persona natural

La app actual ya es multi-tenant; un tenant puede representar una persona natural simplemente creando un tenant/empresa con datos personales.

Con el esquema propuesto:

- Se crea un `Project` de tipo `personal` llamado por ejemplo `Gastos personales`, `Hogar`, `Freelance`.
- Las entradas financieras personales se asocian a ese proyecto.
- Se pueden usar las mismas vistas de `financial_entries` y `currency_rates` para el seguimiento.

## Beneficios de esta extensión

- Conserva la arquitectura multi-tenant actual.
- Evita mezclar finanzas generales y de proyecto mediante el campo `project`.
- Permite usar un mismo sistema para:
  - gestión general de empresa,
  - proyectos específicos,
  - control de gastos personales.

## Pasos de implementación sugeridos

1. Añadir modelos `Project` y `FinancialCategory`.
2. Extender `FinancialEntry` e `Invoice` con `project` y `category`.
3. Crear formularios y vistas para `Project`.
4. Modificar formularios de movimiento y factura para seleccionar proyecto/categoría.
5. Añadir filtros de `project` en listados de `FinancialEntry` y `Invoice`.
6. Añadir vistas de resumen por proyecto y por mes.
7. Actualizar `README.md` y `docs/EXTENSION_SCHEMA.md` con el flujo.

## Ejemplo de uso

### Empresa con proyectos

- Crear `Project` "Refactor web" tipo `client`.
- Registrar todos los ingresos y gastos asociados a ese proyecto.
- Consultar relatório mensual o por proyecto.

### Persona natural

- Crear tenant con nombre propio.
- Crear `Project` "Gastos personales" tipo `personal`.
- Registrar sueldos, servicios, compras y otros gastos.
- Filtrar por mes para ver el balance personal.

## Nota

Este esquema está pensado como base. Para hacerlo aún más robusto se pueden agregar en el futuro:
- presupuestos por proyecto,
- subproyectos,
- métricas de avance,
- importación de gastos bancarios,
- reglas de clasificación automática.
