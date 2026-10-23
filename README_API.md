# SystemManager API Guide

## Autenticación JWT

SystemManager ofrece autenticación por JWT para sus endpoints API.

### Obtener tokens

Solicita usuario y contraseña en `/api/token/`:

```bash
curl -X POST http://localhost:5000/api/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<USUARIO>&password=<CONTRASEÑA>"
```

Respuesta de ejemplo:

```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi..."
}
```

### Renovar access token

Usa el refresh token en `/api/token/refresh/`:

```bash
curl -X POST http://localhost:5000/api/token/refresh/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "refresh=<REFRESH_TOKEN>"
```

Ejemplo de respuesta:

```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi..."
}
```

## Consumo de endpoints API

Todos los endpoints API requieren que el usuario esté autenticado y deben ejecutarse en contexto de tenant.

### Cabecera Authorization

Incluye el token en la cabecera `Authorization`:

```bash
-H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Listar movimientos financieros

```bash
curl http://localhost:5000/api/financial-entries/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Filtros disponibles

- `type`: tipo de movimiento (`income`, `expense`, `account_receivable`, `account_payable`)
- `status`: estado (`pending`, `partial`, `paid`, `cancelled`)
- `date_from`: fecha mínima `YYYY-MM-DD`
- `date_to`: fecha máxima `YYYY-MM-DD`
- `currency`: moneda (`COP`, `USD`, `EUR`, `BINANCE`)
- `page`: número de página
- `page_size`: registros por página

Ejemplo con filtros:

```bash
curl "http://localhost:5000/api/financial-entries/?type=income&status=pending&page=1&page_size=20" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Listar terceros activos

```bash
curl http://localhost:5000/api/third-parties/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Listar tasas de cambio

```bash
curl http://localhost:5000/api/currency-rates/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Uso con sesión Django

Alternativamente, si prefieres usar autenticación por sesión, inicia sesión en el frontend y usa las mismas URLs en el mismo navegador. Los endpoints aceptan `SessionAuthentication`.

## Notas importantes

- El acceso a los endpoints solo funciona si la solicitud se realiza dentro del contexto de un tenant válido.
- Para integraciones externas, usa JWT con el endpoint `/api/token/`.
- Si necesitas permisos más finos, la implementación actual aplica autenticación general e identifica al usuario autenticado.

## API v1 de escritura

Los endpoints anteriores de lectura se mantienen. La API DRF versionada está disponible
bajo `/api/v1/`:

| Recurso | Operaciones |
|---|---|
| `/api/v1/financial-entries/` | Listar, consultar, crear y actualizar movimientos |
| `/api/v1/third-parties/` | Listar, consultar, crear y actualizar terceros |
| `/api/v1/webhooks/` | Listar, consultar, crear y actualizar endpoints webhook |
| `/api/v1/webhook-deliveries/` | Consultar el historial de entregas y sus reintentos |

Usa `POST`, `PUT` o `PATCH` solo con el rol tenant **Administrador de empresa** o
**Operador financiero**. Las lecturas requieren autenticación. Los módulos Finanzas
y Terceros deben estar habilitados en el tenant para usar esos recursos. Los movimientos
no se pueden borrar desde la API y su estado se actualiza por el flujo de pagos.

Cada `POST` requiere `Idempotency-Key`, única por usuario y tenant. Repetir la misma
clave y el mismo cuerpo devuelve la respuesta original; reutilizarla con otro cuerpo
responde `409 Conflict`.

Ejemplo de creación de tercero:

```bash
curl -X POST http://localhost:5000/api/v1/third-parties/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: crm-tercero-001" \
  -d '{"name":"Proveedor de prueba","third_party_type":"supplier","email":"compras@example.com"}'
```

### Webhooks

Crea un endpoint con una URL HTTPS pública, una clave secreta elegida por la integración y
uno o más eventos en `event_types`. No se aceptan destinos locales, IP privadas ni
credenciales embebidas en la URL. La clave no vuelve a incluirse en las respuestas y no
se puede editar; para rotarla, crea otro endpoint y desactiva el anterior.
Eventos disponibles:

- `invoice.created`
- `invoice.paid`
- `payment.registered`
- `financial_entry.created`

Las entregas se encolan en Celery y quedan consultables en
`/api/v1/webhook-deliveries/`. Se reintentan hasta cinco veces ante errores de red,
HTTP 429 o HTTP 5xx; respuestas HTTP 4xx (salvo 429) se marcan como fallidas. Cada
solicitud incluye `X-SystemManager-Event`, `X-SystemManager-Delivery` y
`X-SystemManager-Signature`. La firma es HMAC-SHA256 del cuerpo JSON exacto, codificada
como `sha256=<hex>`, y se calcula con la clave secreta configurada. Las redirecciones
no se siguen.

## Script de ejemplo

También puedes usar el script `scripts/api_test.sh` para probar rápidamente la API:

```bash
chmod +x scripts/api_test.sh
./scripts/api_test.sh http://localhost:5000 <usuario> <contraseña>
```
