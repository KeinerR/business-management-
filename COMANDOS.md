# Comandos Docker Compose (Django)

Servicio en compose: web
Contenedor: systemmanager_web

## Levantar y detener

- Levantar en primer plano:
  docker compose up

- Levantar en segundo plano:
  docker compose up -d

- Detener y borrar contenedores/red:
  docker compose down

## Logs

- Ver logs del servicio:
  docker compose logs -f web

- Ver logs por nombre de contenedor (docker directo):
  docker logs -f systemmanager_web

## Django dentro del contenedor

- Ejecutar migraciones:
  docker compose exec web python manage.py migrate

- Crear migraciones:
  docker compose exec web python manage.py makemigrations

- Crear superusuario (interactivo):
  docker compose exec web python manage.py createsuperuser

- Shell de Django:
  docker compose exec web python manage.py shell

## Comandos one-shot (sin contenedor ya levantado)

- Correr migraciones una vez:
  docker compose run --rm web python manage.py migrate

- Crear superusuario una vez:
  docker compose run --rm web python manage.py createsuperuser

## Superusuario sin prompts

DJANGO_SUPERUSER_USERNAME=admin \
DJANGO_SUPERUSER_EMAIL=admin@local.com \
DJANGO_SUPERUSER_PASSWORD=admin123 \
docker compose run --rm web python manage.py createsuperuser --noinput

## Regla clave

En Docker Compose se usa el nombre del servicio (web), no container_name.
