#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/alessarsolutions}"
BACKEND_DIR="$APP_DIR/backend"
ENV_FILE="$BACKEND_DIR/.env"
SUPERVISOR_CONFIG="$APP_DIR/deploy/cyberpanel/supervisord.conf"
PUBLIC_STATIC_DIR="${PUBLIC_STATIC_DIR:-$HOME/public_html/static}"

test -f "$BACKEND_DIR/manage.py" || { echo "Missing $BACKEND_DIR/manage.py" >&2; exit 1; }
test -f "$ENV_FILE" || { echo "Missing $ENV_FILE" >&2; exit 1; }
grep -Eq '^DJANGO_DEBUG=false$' "$ENV_FILE" || { echo "DJANGO_DEBUG must be false" >&2; exit 1; }
grep -Eq '^DB_ENGINE=mysql$' "$ENV_FILE" || { echo "DB_ENGINE must be mysql" >&2; exit 1; }
grep -Eq '^DB_PASSWORD=.+$' "$ENV_FILE" || { echo "DB_PASSWORD is empty" >&2; exit 1; }
grep -Eq '^INNOVATEMR_API_TOKEN=.+$' "$ENV_FILE" || { echo "INNOVATEMR_API_TOKEN is empty" >&2; exit 1; }

home_path="$(realpath -m "$HOME")"
static_path="$(realpath -m "$PUBLIC_STATIC_DIR")"
case "$static_path" in
  "$home_path"/public_html/static|"$home_path"/public_html/static/*) ;;
  *) echo "PUBLIC_STATIC_DIR must stay inside $HOME/public_html/static" >&2; exit 1 ;;
esac

mkdir -p "$HOME/app_logs" "$HOME/tmp" "$HOME/redis-data" "$PUBLIC_STATIC_DIR"
chmod 700 "$HOME/tmp"
chmod 600 "$ENV_FILE"

cd "$BACKEND_DIR"
PYTHON_BIN="${PYTHON_BIN:-}"
if test -z "$PYTHON_BIN"; then
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.11)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi
if ! test -x .venv/bin/python; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
rsync -a --delete "$BACKEND_DIR/staticfiles/" "$PUBLIC_STATIC_DIR/"

SUPERVISORCTL="$BACKEND_DIR/.venv/bin/supervisorctl"
SUPERVISORD="$BACKEND_DIR/.venv/bin/supervisord"
if "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" pid >/dev/null 2>&1; then
  "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" reread
  "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" update
  "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" restart all
else
  "$SUPERVISORD" -c "$SUPERVISOR_CONFIG"
fi

cron_line="@reboot $SUPERVISORD -c $SUPERVISOR_CONFIG"
existing_cron="$(crontab -l 2>/dev/null || true)"
if ! grep -Fqx "$cron_line" <<<"$existing_cron"; then
  { printf '%s\n' "$existing_cron"; printf '%s\n' "$cron_line"; } | sed '/^[[:space:]]*$/d' | crontab -
fi

sleep 6
"$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status
curl --fail --silent --show-error --head http://127.0.0.1:8091/login/ >/dev/null
echo "Backend is healthy on private port 127.0.0.1:8091"
