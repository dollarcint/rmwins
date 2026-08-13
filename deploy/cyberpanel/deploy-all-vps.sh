#!/usr/bin/env bash
set -Eeuo pipefail

umask 027

REPOSITORY_URL="https://github.com/kanik-snippet/alessarsolutions.git"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
CHECKOUT_DIR="/opt/alessar-deploy/repository"
CHECKOUT_ROOT="/opt/alessar-deploy"
NODE_BIN_DIR="/opt/node/bin"

FRONTEND_USER="aless4284"
FRONTEND_HOME="/home/alessarsolutions.in"
FRONTEND_APP="$FRONTEND_HOME/alessarsolutions"
FRONTEND_PUBLIC="$FRONTEND_HOME/public_html"

BACKEND_USER="apial8464"
BACKEND_HOME="/home/api.alessarsolutions.in"
BACKEND_APP="$BACKEND_HOME/alessarsolutions"
BACKEND_DIR="$BACKEND_APP/backend"
BACKEND_ENV="$BACKEND_DIR/.env"
SUPERVISOR_CONFIG="$BACKEND_APP/deploy/cyberpanel/supervisord.conf"
SUPERVISORCTL="$BACKEND_DIR/.venv/bin/supervisorctl"

STATE_DIR="/var/lib/alessar-deploy"
BACKUP_ROOT="$BACKEND_HOME/backups"

log() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
    printf '\nDEPLOY FAILED: %s\n' "$*" >&2
    exit 1
}

trap 'printf "\nDEPLOY FAILED at line %s. Existing services were not deliberately removed.\n" "$LINENO" >&2' ERR

test "${EUID:-$(id -u)}" -eq 0 || fail "Run this command as root."
command -v flock >/dev/null || fail "flock is required."
command -v git >/dev/null || fail "git is required."
command -v rsync >/dev/null || fail "rsync is required."
command -v curl >/dev/null || fail "curl is required."
test -x "$NODE_BIN_DIR/node" || fail "Node.js is missing from $NODE_BIN_DIR."
test -x "$NODE_BIN_DIR/npm" || fail "npm is missing from $NODE_BIN_DIR."
test -f "$BACKEND_ENV" || fail "Protected backend environment file is missing: $BACKEND_ENV"

install -d -m 0750 "$STATE_DIR" "$CHECKOUT_ROOT" "$BACKUP_ROOT"
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || fail "Another Alessar deployment is already running."

log "Fetching GitHub branch $DEPLOY_BRANCH"
if test ! -d "$CHECKOUT_DIR/.git"; then
    if test -d "$CHECKOUT_DIR"; then
        test -z "$(find "$CHECKOUT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" \
            || fail "$CHECKOUT_DIR exists but is not an empty Git checkout."
        rmdir "$CHECKOUT_DIR"
    fi
    git clone --filter=blob:none --branch "$DEPLOY_BRANCH" "$REPOSITORY_URL" "$CHECKOUT_DIR"
else
    git -C "$CHECKOUT_DIR" remote set-url origin "$REPOSITORY_URL"
    git -C "$CHECKOUT_DIR" fetch --prune origin "$DEPLOY_BRANCH"
    git -C "$CHECKOUT_DIR" reset --hard HEAD
    git -C "$CHECKOUT_DIR" checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
    git -C "$CHECKOUT_DIR" reset --hard "origin/$DEPLOY_BRANCH"
fi

REVISION="$(git -C "$CHECKOUT_DIR" rev-parse HEAD)"
SHORT_REVISION="$(git -C "$CHECKOUT_DIR" rev-parse --short HEAD)"
log "Deploying revision $SHORT_REVISION"

BACKUP_DIR="$BACKUP_ROOT/deploy-$(date '+%Y%m%d-%H%M%S')-$SHORT_REVISION"
install -d -m 0700 -o "$BACKEND_USER" -g "$BACKEND_USER" "$BACKUP_DIR"
install -m 0600 -o "$BACKEND_USER" -g "$BACKEND_USER" "$BACKEND_ENV" "$BACKUP_DIR/backend.env"
if test -f "$STATE_DIR/last_revision"; then
    install -m 0600 "$STATE_DIR/last_revision" "$BACKUP_DIR/previous_revision"
fi

log "Building React frontend as $FRONTEND_USER"
install -d -m 0755 -o "$FRONTEND_USER" -g "$FRONTEND_USER" \
    "$FRONTEND_APP/frontend" "$FRONTEND_APP/deploy" "$FRONTEND_PUBLIC"
rsync -a --delete --chown="$FRONTEND_USER:$FRONTEND_USER" \
    --exclude node_modules/ --exclude dist/ \
    "$CHECKOUT_DIR/frontend/" "$FRONTEND_APP/frontend/"
rsync -a --delete --chown="$FRONTEND_USER:$FRONTEND_USER" \
    "$CHECKOUT_DIR/deploy/" "$FRONTEND_APP/deploy/"
runuser -u "$FRONTEND_USER" -- env \
    HOME="$FRONTEND_HOME" \
    PATH="$NODE_BIN_DIR:/usr/local/bin:/usr/bin:/bin" \
    bash -c "cd '$FRONTEND_APP/frontend' && npm ci --no-audit --no-fund && VITE_DASHBOARD_URL=https://api.alessarsolutions.in npm run build"
rsync -a --delete --exclude .well-known/ --chown="$FRONTEND_USER:$FRONTEND_USER" \
    "$FRONTEND_APP/frontend/dist/" "$FRONTEND_PUBLIC/"

log "Updating Django backend as $BACKEND_USER"
rsync -a --delete --chown="$BACKEND_USER:$BACKEND_USER" \
    --exclude .env \
    --exclude .venv/ \
    --exclude staticfiles/ \
    --exclude __pycache__/ \
    --exclude '*.pyc' \
    --exclude db.sqlite3 \
    --exclude prescreener_vault.sqlite3 \
    "$CHECKOUT_DIR/backend/" "$BACKEND_DIR/"
rsync -a --delete --chown="$BACKEND_USER:$BACKEND_USER" \
    "$CHECKOUT_DIR/deploy/" "$BACKEND_APP/deploy/"
chmod 0600 "$BACKEND_ENV"

runuser -u "$BACKEND_USER" -- env HOME="$BACKEND_HOME" bash -c "
    set -Eeuo pipefail
    cd '$BACKEND_DIR'
    .venv/bin/pip install --disable-pip-version-check -r requirements.txt
    .venv/bin/python manage.py migrate --noinput
    .venv/bin/python manage.py migrate --database=prescreener_vault --noinput
    .venv/bin/python manage.py collectstatic --noinput
    .venv/bin/python manage.py check --deploy
"

install -d -m 0755 -o "$BACKEND_USER" -g "$BACKEND_USER" "$BACKEND_HOME/public_html/static"
rsync -a --delete --chown="$BACKEND_USER:$BACKEND_USER" \
    "$BACKEND_DIR/staticfiles/" "$BACKEND_HOME/public_html/static/"

log "Restarting Alessar application services"
runuser -u "$BACKEND_USER" -- env HOME="$BACKEND_HOME" \
    "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" reread
runuser -u "$BACKEND_USER" -- env HOME="$BACKEND_HOME" \
    "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" update
runuser -u "$BACKEND_USER" -- env HOME="$BACKEND_HOME" \
    "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" restart all
systemctl restart alessar-frontend.service

sleep 8

log "Running service and HTTP health checks"
# Redis databases 2 and 3 contain only rebuildable Django caches. Redis is
# persistent for Celery, so clear these cache databases after a restart to
# prevent an old project count/filter snapshot from becoming authoritative.
redis-cli -p 6381 -n 2 FLUSHDB >/dev/null
redis-cli -p 6381 -n 3 FLUSHDB >/dev/null
SUPERVISOR_STATUS="$(runuser -u "$BACKEND_USER" -- env HOME="$BACKEND_HOME" \
    "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status)"
printf '%s\n' "$SUPERVISOR_STATUS"
if printf '%s\n' "$SUPERVISOR_STATUS" | awk '$2 != "RUNNING" { bad=1 } END { exit bad }'; then
    :
else
    fail "One or more backend Supervisor programs are not RUNNING."
fi

systemctl is-active --quiet alessar-frontend.service || fail "Frontend service is not active."
systemctl is-active --quiet alessar-mysql.service || fail "Alessar MariaDB service is not active."
curl --fail --silent --show-error --max-time 20 http://127.0.0.1:8092/ >/dev/null
curl --fail --silent --show-error --max-time 20 \
    -H 'Host: api.alessarsolutions.in' -H 'X-Forwarded-Proto: https' \
    http://127.0.0.1:8091/login/ >/dev/null
curl --fail --silent --show-error --max-time 30 https://alessarsolutions.in/ >/dev/null
curl --fail --silent --show-error --max-time 30 https://api.alessarsolutions.in/login/ >/dev/null

printf '%s\n' "$REVISION" > "$STATE_DIR/last_revision"
chmod 0600 "$STATE_DIR/last_revision"

log "DEPLOY SUCCESS: $SHORT_REVISION is live on frontend and backend"
