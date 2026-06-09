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

## Script de ejemplo

También puedes usar el script `scripts/api_test.sh` para probar rápidamente la API:

```bash
chmod +x scripts/api_test.sh
./scripts/api_test.sh http://localhost:5000 <usuario> <contraseña>
```
