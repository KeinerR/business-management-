#!/bin/bash
set -e

echo "Verificando e instalando dependencias de Python desde requirements.txt..."
pip install -r requirements.txt

# Ejecuta el comando principal del contenedor (lo que se define en CMD en el Dockerfile)
exec "$@"