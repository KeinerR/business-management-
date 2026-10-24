FROM python:3.13-slim-trixie

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .

# psycopg[binary] supplies libpq; the remaining packages use wheels or pure Python.
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/media /app/staticfiles /var/lib/celery \
    && chown -R app:app /app /var/lib/celery

COPY --chown=app:app . .

USER app
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
