#!/bin/sh

# Script de prueba para los endpoints API de SystemManager.
# Uso: ./scripts/api_test.sh [BASE_URL] [USERNAME] [PASSWORD]
# Ejemplo: ./scripts/api_test.sh http://localhost:5000 admin mypassword

BASE_URL="${1:-http://localhost:5000}"
USERNAME="${2:-admin}"
PASSWORD="${3:-admin}"

printf "Obteniendo token para usuario %s en %s...\n" "$USERNAME" "$BASE_URL"

TOKEN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$USERNAME&password=$PASSWORD")

ACCESS_TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin).get("access", ""))')
REFRESH_TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin).get("refresh", ""))')

if [ -z "$ACCESS_TOKEN" ]; then
  echo "Error obteniendo token. Respuesta:"$TOKEN_RESPONSE
  exit 1
fi

printf "Access token obtenido.\n\n"
printf "=== Financial Entries ===\n"
curl -s "$BASE_URL/api/financial-entries/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | python3 -m json.tool

printf "\n=== Third Parties ===\n"
curl -s "$BASE_URL/api/third-parties/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | python3 -m json.tool

printf "\n=== Currency Rates ===\n"
curl -s "$BASE_URL/api/currency-rates/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | python3 -m json.tool

printf "\nRefresh token:\n%s\n" "$REFRESH_TOKEN"
