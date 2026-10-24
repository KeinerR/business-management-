# Sistema de Facturas - Guía de Uso

## 📋 Descripción

El módulo de Facturas permite crear, gestionar y exportar facturas en PDF. Incluye:

- ✅ Crear facturas con múltiples líneas de detalle
- ✅ Editar facturas en estado "borrador"
- ✅ Ver detalles completos de la factura
- ✅ Exportar a PDF con formato profesional
- ✅ Filtrar por estado y fecha de vencimiento
- ✅ Registro de auditoría de todas las operaciones

## 🚀 Funcionalidades

### Estados de Factura

| Estado | Descripción | Acciones Permitidas |
|--------|-------------|-------------------|
| **draft** | Borrador | Editar, Emitir, Anular, Ver PDF |
| **issued** | Emitida | Ver, PDF |
| **paid** | Pagada | Ver, PDF |
| **overdue** | Vencida | Ver, PDF |
| **cancelled** | Cancelada | Ver |

### Permisos Requeridos

- **Crear/Editar**: Administrador de empresa, Operador financiero
- **Ver**: Todos los usuarios autenticados
- **Eliminar**: no permitido; utilizar el flujo de anulación.
- **Exportar PDF**: Todos los usuarios autenticados

## 📊 URLs del Módulo

```
/invoices/                          # Lista de facturas
/invoices/create/                  # Crear nueva factura
/invoices/<id>/                    # Ver detalle
/invoices/<id>/edit/               # Editar (solo borrador)
/invoices/<id>/pdf/                # Descargar PDF
/invoices/<id>/issue/              # Emitir y crear cuenta por cobrar
/invoices/<id>/cancel/             # Anular según restricciones del documento
```

## 🗄️ Modelos de Base de Datos

### Invoice

```python
- invoice_number: CharField (único)
- business: ForeignKey(Business)
- third_party: ForeignKey(ThirdParty, nullable)
- status: CharField(choices: draft, issued, paid, overdue, cancelled)
- issue_date: DateField
- due_date: DateField (nullable)
- subtotal: DecimalField
- tax_rules: ManyToManyField(TaxRule), reglas tributarias del tenant
- retention_amount: DecimalField (calculado)
- tax_amount: DecimalField (calculado)
- total: DecimalField (calculado)
- currency: CharField (COP, USD, EUR, etc.)
- description: TextField (nullable)
- notes: TextField (nullable)
- financial_entry: OneToOneField(FinancialEntry, nullable)
- created_by: ForeignKey(User)
- created_at: DateTimeField
- updated_at: DateTimeField
```

### InvoiceItem

```python
- invoice: ForeignKey(Invoice)
- description: CharField
- quantity: DecimalField
- unit_price: DecimalField
- subtotal: DecimalField (quantity × unit_price)
```

## 💾 Dependencias

- `reportlab==4.0.9` - Generación de PDF

## 🔧 Instalación

Las dependencias están instaladas en el contenedor Docker. Si necesitas instalar manualmente:

```bash
pip install reportlab==4.0.9
```

## 📝 Ejemplo de Flujo

1. **Crear Factura**
   - Ir a "Invoices" → "New Invoice"
   - Llenar información general (número, cliente, fechas)
   - Agregar líneas de detalle (descripción, cantidad, precio)
   - El sistema calcula automáticamente IVA y total
   - Guardar como "draft"

2. **Editar Factura**
   - Solo posible si está en estado "draft"
   - Cambiar datos, agregar/quitar líneas
   - Guardar cambios

3. **Exportar PDF**
   - Ir a detalle de factura
   - Clic en "Download PDF"
   - Se genera PDF profesional con:
     - Información de empresa y cliente
     - Líneas de detalle
     - Totales con IVA

4. **Cambiar Estado**
   - Emitir desde la acción dedicada de la factura.
   - La emisión crea una cuenta por cobrar una sola vez; los pagos actualizan los estados.

## 🎨 Diseño de PDF

El PDF generado incluye:
- Encabezado con número de factura
- Información de empresa y cliente
- Tabla de líneas de detalle
- Cálculos de subtotal, IVA y total
- Formato profesional con colores corporativos

## 📊 Auditoría

Todas las operaciones se registran en `AuditEvent`:
- Creación de factura
- Ediciones
- Cambios de estado
- Eliminaciones
- Exportaciones a PDF

## ⚠️ Consideraciones

- Las facturas solo pueden ser editadas en estado "draft"
- El número de factura debe ser único por empresa
- El cálculo de impuestos y retenciones se realiza con las reglas seleccionadas
- Los PDFs se generan bajo demanda sin guardar en servidor

## 🔐 Seguridad

- Todas las vistas requieren `@login_required` y `@tenant_required`
- Acceso restringido por grupos de permisos
- CSRF protection en todos los formularios
- Auditería completa de operaciones

## 🐛 Solución de Problemas

### "ReportLab no está instalado"
```bash
# En contenedor Docker
docker compose exec web pip install reportlab==4.0.9

# O reconstruir imagen
docker compose down
docker compose up -d --build
```

### PDF sale vacío o con errores
- Verificar que InvoiceItem.objects existe
- Revisar permisos del usuario
- Comprobar que reportlab esté importado correctamente

### Factura no se guarda
- Verificar que Business exista
- Comprobar que el número de factura sea único
- Revisar errores en la consola de Django

## 📚 Archivos Relacionados

- `businessmanagement/views.py` - Vistas invoice_*
- `businessmanagement/urls.py` - Rutas
- `businessmanagement/forms.py` - InvoiceForm, InvoiceItemForm
- `tenantdata/models.py` - Invoice, InvoiceItem models
- `businessmanagement/template/tenant/invoice_*.html` - Templates
- `tenantdata/migrations/0004_invoice_invoiceitem_and_more.py` - Migración

---

**Última revisión**: 24 de octubre de 2026
**Referencia vigente**: ESTADO_IMPLEMENTACION.md
