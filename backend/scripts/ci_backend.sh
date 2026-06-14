#!/bin/sh
set -eu

pip install --no-cache-dir -r requirements-dev.txt

env \
  KALMIO_ENV=production \
  DJANGO_DEBUG=false \
  DJANGO_SECRET_KEY=ci-production-secret-not-for-runtime-9f46c0b1a5c24b42a3d7d0eaf5a8c1de \
  DJANGO_ALLOWED_HOSTS=api.kalmio.example \
  CORS_ALLOWED_ORIGINS=https://app.kalmio.example \
  CSRF_TRUSTED_ORIGINS=https://app.kalmio.example \
  python manage.py check --deploy --fail-level WARNING

python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py migrate --check
pytest
