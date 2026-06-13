#!/bin/bash

set -euo pipefail

echo "📦 Collecting static files"
python manage.py collectstatic --noinput || {
    echo "❌ Failed to collect static files"; exit 1;
}

echo "🏗  Running shared schema migrations (public tables)"
python manage.py migrate_schemas --shared --noinput || {
    echo "❌ Failed to run shared migrations"; exit 1;
}

echo "🏗  Running tenant schema migrations (all tenants)"
python manage.py migrate_schemas --noinput || {
    echo "❌ Failed to run tenant migrations"; exit 1;
}

echo "🚀 Starting Gunicorn server"
exec gunicorn inventory_core.wsgi:application \
  --bind 0.0.0.0:8400 \
  --workers 3 \
  --access-logfile - \
  --error-logfile -
