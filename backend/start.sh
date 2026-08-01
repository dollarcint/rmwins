#!/usr/bin/env bash
set -o errexit

python manage.py migrate --no-input
python manage.py ensure_superuser
exec gunicorn surveyboard.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 60
