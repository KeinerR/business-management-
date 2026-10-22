#!/bin/bash
set -e

echo "Verificando e instalando dependencias de Python desde requirements.txt..."
pip install -r requirements.txt

echo "Asegurando tenants y módulos..."
python manage.py ensure_dev_tenants

echo "Creando cuentas bancarias de ejemplo..."
python manage.py create_sample_banking

# Ejecuta el comando principal del contenedor
exec "$@"
