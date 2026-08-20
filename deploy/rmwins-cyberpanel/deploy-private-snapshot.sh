#!/usr/bin/env bash
# Deploy a trusted local source snapshot to the private RMWins services.
#
# This script deliberately does not install or reload any public Nginx vhost,
# request a certificate, change DNS, open firewall ports, or stop Alessar.
# Upload a root-owned mode-0600 tar.gz snapshot, install this wrapper as
# /var/lib/rmwins-deploy/deploy-private-snapshot.sh (root:root mode 0700), then:
#   SNAPSHOT_ARCHIVE=/var/tmp/rmwins-snapshot.tar.gz \
#     /var/lib/rmwins-deploy/deploy-private-snapshot.sh

set -Eeuo pipefail
umask 027

APP_USER="wwwrm1759"
APP_GROUP="wwwrm1759"
APP_HOME="/home/www.rmwinsights.com"
APP_DIR="$APP_HOME/rmwins"
BACKEND_DIR="$APP_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
CONFIG_DIR="$APP_HOME/.config/rmwins"
BACKEND_ENV="$CONFIG_DIR/backend.env"
REDIS_PERSISTENT_CONFIG="$CONFIG_DIR/redis-6382.conf"
REDIS_CACHE_CONFIG="$CONFIG_DIR/redis-6383.conf"
ADMIN_CREDENTIALS="$CONFIG_DIR/admin-credentials"
FRONTEND_RELEASE="$APP_HOME/app/frontend-dist"
STATE_DIR="/var/lib/rmwins-deploy"
BACKUP_ROOT="/var/backups/rmwins"
SNAPSHOT_ARCHIVE="${SNAPSHOT_ARCHIVE:-}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.11}"
SUPERVISOR_CONFIG="$APP_DIR/deploy/rmwins-cyberpanel/supervisord.conf"
SUPERVISORCTL="$VENV_DIR/bin/supervisorctl"
PG_SOCKET_DIR="/var/run/postgresql"
APP_SAFE_PATH="$VENV_DIR/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/bin"
PG_SAFE_PATH="/usr/pgsql-16/bin:/usr/local/bin:/usr/bin:/bin"

STAGING_DIR=""
TEMP_FILES=()
RMWINS_SERVICES_STOPPED=0

log() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
    printf '\nRMWINS PRIVATE DEPLOY FAILED: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local path
    for path in "${TEMP_FILES[@]:-}"; do
        test -n "$path" && rm -f -- "$path"
    done
    if test -n "$STAGING_DIR" && test -d "$STAGING_DIR"; then
        case "$STAGING_DIR" in
            /var/tmp/rmwins-stage.*) rm -rf -- "$STAGING_DIR" ;;
        esac
    fi
}

on_error() {
    printf '\nFailure at line %s; public routing and legacy Alessar services were not deliberately changed.\n' \
        "$LINENO" >&2
    if test "$RMWINS_SERVICES_STOPPED" -eq 1; then
        systemctl stop rmwins-frontend.service rmwins-supervisor.service >/dev/null 2>&1 || true
        printf 'The private RMWins services remain stopped to avoid running mixed code/schema state.\n' >&2
    fi
}

trap cleanup EXIT
trap on_error ERR

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command is missing: $1"
}

env_value() {
    local key="$1" count line
    count="$(grep -c -E "^${key}=" "$BACKEND_ENV" || true)"
    test "$count" -eq 1 || fail "Expected exactly one $key entry in $BACKEND_ENV"
    line="$(grep -m1 -E "^${key}=" "$BACKEND_ENV")"
    printf '%s' "${line#*=}"
}

assert_exact_target() {
    local actual
    actual="$(realpath -m "$1")"
    test "$actual" = "$2" || fail "Resolved path $actual does not equal protected target $2"
}

reject_symlink_or_nonregular() {
    local path="$1"
    test ! -L "$path" || fail "Protected path must not be a symlink: $path"
    if test -e "$path"; then
        test -f "$path" || fail "Protected path must be a regular file: $path"
    fi
}

reject_symlink_or_nondirectory() {
    local path="$1"
    test ! -L "$path" || fail "Directory path must not be a symlink: $path"
    if test -e "$path"; then
        test -d "$path" || fail "Expected a directory: $path"
    fi
}

run_app_clean() {
    runuser -u "$APP_USER" -- env -i \
        HOME="$APP_HOME" USER="$APP_USER" LOGNAME="$APP_USER" \
        LANG=C.UTF-8 PATH="$APP_SAFE_PATH" "$@"
}

run_root_python() {
    env -i HOME=/root USER=root LOGNAME=root LANG=C.UTF-8 \
        PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        "$PYTHON_BIN" "$@"
}

pg_admin_psql() {
    runuser -u postgres -- env -i \
        HOME=/var/lib/pgsql USER=postgres LOGNAME=postgres LANG=C.UTF-8 \
        PATH="$PG_SAFE_PATH" PGHOST="$PG_SOCKET_DIR" PGPORT=5432 \
        PGUSER=postgres PGDATABASE=postgres \
        "$PSQL_BIN" --no-psqlrc "$@"
}

pg_admin_dump() {
    local database="$1"
    runuser -u postgres -- env -i \
        HOME=/var/lib/pgsql USER=postgres LOGNAME=postgres LANG=C.UTF-8 \
        PATH="$PG_SAFE_PATH" \
        "$PG_DUMP_BIN" --host="$PG_SOCKET_DIR" --port=5432 \
        --username=postgres --dbname="$database" --format=custom
}

pg_password_psql() {
    # Feed the password through a pipe into a clean root-only process. It is
    # never placed in argv or an env(1) assignment visible in /proc/cmdline.
    local password="$1"
    shift
    printf '%s\n' "$password" | env -i \
        HOME=/root USER=root LOGNAME=root LANG=C.UTF-8 \
        PATH="$PG_SAFE_PATH" \
        /bin/bash --noprofile --norc -c '
            IFS= read -r PGPASSWORD
            export PGPASSWORD
            exec "$@" </dev/null
        ' pg-password "$PSQL_BIN" --no-psqlrc "$@"
}

restart_or_start() {
    if systemctl is-active --quiet "$1"; then
        systemctl restart "$1"
    else
        systemctl start "$1"
    fi
}

test "${EUID:-$(id -u)}" -eq 0 || fail "Run as root."
test -n "$SNAPSHOT_ARCHIVE" || fail "Set SNAPSHOT_ARCHIVE to the uploaded tar.gz file."
test ! -L "$SNAPSHOT_ARCHIVE" || fail "Snapshot archive must not be a symlink."
test -f "$SNAPSHOT_ARCHIVE" || fail "Snapshot does not exist: $SNAPSHOT_ARCHIVE"
test "$(stat -c %U "$SNAPSHOT_ARCHIVE")" = "root" || fail "Snapshot archive must be root-owned."
SNAPSHOT_MODE="$(stat -c %a "$SNAPSHOT_ARCHIVE")"
test "$SNAPSHOT_MODE" = "600" || fail "Uploaded snapshot must have exact mode 0600."

for command_name in awk curl find flock git grep install nginx openssl pg_dump pg_isready psql \
    realpath redis-cli redis-server rsync runuser sha256sum ss stat systemctl systemd-analyze tar; do
    require_command "$command_name"
done
PSQL_BIN="$(command -v psql)"
PG_DUMP_BIN="$(command -v pg_dump)"
test -x "$PYTHON_BIN" || fail "Python 3.11 is missing: $PYTHON_BIN"
test -x /opt/node/bin/node || fail "Node.js is missing: /opt/node/bin/node"
test -x /opt/node/bin/npm || fail "npm is missing: /opt/node/bin/npm"
test -d "$PG_SOCKET_DIR" || fail "PostgreSQL socket directory is missing: $PG_SOCKET_DIR"

USER_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
test "$USER_HOME" = "$APP_HOME" || fail "$APP_USER home is $USER_HOME, expected $APP_HOME"
test ! -L "$APP_HOME" || fail "Refusing a symlinked application home: $APP_HOME"
assert_exact_target "$APP_DIR" "$APP_DIR"
assert_exact_target "$CONFIG_DIR" "$CONFIG_DIR"
assert_exact_target "$FRONTEND_RELEASE" "$FRONTEND_RELEASE"
reject_symlink_or_nondirectory "$APP_HOME/.config"
reject_symlink_or_nondirectory "$CONFIG_DIR"
reject_symlink_or_nondirectory "$APP_DIR"
reject_symlink_or_nondirectory "$APP_HOME/app"
reject_symlink_or_nondirectory "$FRONTEND_RELEASE"
reject_symlink_or_nondirectory "$STATE_DIR"
reject_symlink_or_nondirectory "$BACKUP_ROOT"
for protected_file in "$BACKEND_ENV" "$REDIS_PERSISTENT_CONFIG" \
    "$REDIS_CACHE_CONFIG" "$ADMIN_CREDENTIALS"; do
    reject_symlink_or_nonregular "$protected_file"
done

install -d -m 0750 -o root -g root "$STATE_DIR"
install -d -m 0700 -o root -g root "$BACKUP_ROOT"
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || fail "Another RMWins deployment is already running."

SELF_PATH="$(realpath -e "${BASH_SOURCE[0]}")"
case "$SELF_PATH" in
    "$STATE_DIR"/*) ;;
    *) fail "Execute the wrapper from the root-owned $STATE_DIR directory." ;;
esac
test ! -L "${BASH_SOURCE[0]}" || fail "Deploy wrapper must not be a symlink."
test "$(stat -c %U "$SELF_PATH")" = "root" || fail "Deploy wrapper must be root-owned."
test "$(stat -c %a "$SELF_PATH")" = "700" || fail "Deploy wrapper must have exact mode 0700."

SOURCE_SNAPSHOT_SHA256="$(sha256sum "$SNAPSHOT_ARCHIVE" | awk '{print $1}')"
PROTECTED_SNAPSHOT="$STATE_DIR/snapshot-$SOURCE_SNAPSHOT_SHA256.tar.gz"
reject_symlink_or_nonregular "$PROTECTED_SNAPSHOT"
if test ! -f "$PROTECTED_SNAPSHOT"; then
    install -m 0600 -o root -g root "$SNAPSHOT_ARCHIVE" "$PROTECTED_SNAPSHOT"
fi
test "$(stat -c %U "$PROTECTED_SNAPSHOT")" = "root" \
    || fail "Protected snapshot must be root-owned."
test "$(stat -c %a "$PROTECTED_SNAPSHOT")" = "600" \
    || fail "Protected snapshot must have exact mode 0600."
test "$(sha256sum "$PROTECTED_SNAPSHOT" | awk '{print $1}')" = "$SOURCE_SNAPSHOT_SHA256" \
    || fail "Protected snapshot hash differs from the uploaded archive."
SNAPSHOT_ARCHIVE="$PROTECTED_SNAPSHOT"

log "Checking isolation and legacy service safety"
for port in 6382 6383 8093 8094; do
    if ss -H -ltn | awk '{print $4}' | grep -Eq "(^|:)${port}$"; then
        case "$port" in
            6382|6383|8093) systemctl is-active --quiet rmwins-supervisor.service \
                || fail "Port $port is occupied before the RMWins service is active." ;;
            8094) systemctl is-active --quiet rmwins-frontend.service \
                || fail "Port $port is occupied before the RMWins frontend is active." ;;
        esac
    fi
done
systemctl is-active --quiet postgresql.service || fail "PostgreSQL is not active."
PG_CLIENT_VERSION="$(env -i PATH="$PG_SAFE_PATH" "$PSQL_BIN" --version)"
PG_CLIENT_MAJOR="$(printf '%s\n' "$PG_CLIENT_VERSION" | awk '{split($3,v,"."); print v[1]}')"
test "$PG_CLIENT_MAJOR" = "16" || fail "PostgreSQL 16 client is required; found $PG_CLIENT_VERSION."
PG_SERVER_MAJOR="$(pg_admin_psql -Atqc \
    "SELECT current_setting('server_version_num')::integer / 10000")"
test "$PG_SERVER_MAJOR" = "16" || fail "PostgreSQL server major is $PG_SERVER_MAJOR, expected 16."
PG_LISTEN="$(pg_admin_psql -Atqc "SHOW listen_addresses")"
case ",$PG_LISTEN," in
    *,localhost,*|*,127.0.0.1,*) ;;
    *) fail "PostgreSQL is not listening on loopback: $PG_LISTEN" ;;
esac
PG_LISTENERS="$(ss -H -ltn | awk '$4 ~ /:5432$/ {print $4}')"
test -n "$PG_LISTENERS" || fail "PostgreSQL has no TCP listener on port 5432."
if printf '%s\n' "$PG_LISTENERS" \
    | grep -Ev '^(127\.0\.0\.1|\[::1\]):5432$' | grep -q .; then
    fail "PostgreSQL 5432 has a non-loopback listener: $PG_LISTENERS"
fi
HBA_ERRORS="$(pg_admin_psql -Atqc \
    "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL")"
test "$HBA_ERRORS" = "0" || fail "PostgreSQL HBA contains parse errors."
HBA_INSECURE="$(pg_admin_psql -Atqc \
    "SELECT count(*) FROM pg_hba_file_rules
     WHERE type IN ('host','hostssl','hostnossl')
       AND address IN ('127.0.0.1','::1')
       AND NOT ('replication'=ANY(database))
       AND auth_method <> 'scram-sha-256'")"
test "$HBA_INSECURE" = "0" || fail "A non-replication loopback HBA rule is not SCRAM."
HBA_SCRAM_IPV4="$(pg_admin_psql -Atqc \
    "SELECT count(*) FROM pg_hba_file_rules
     WHERE type IN ('host','hostssl') AND address='127.0.0.1'
       AND auth_method='scram-sha-256'
       AND 'all'=ANY(database) AND 'all'=ANY(user_name)")"
test "$HBA_SCRAM_IPV4" -ge 1 || fail "No generic SCRAM IPv4 loopback HBA rule is active."
if printf '%s\n' "$PG_LISTENERS" | grep -Fxq '[::1]:5432'; then
    HBA_SCRAM_IPV6="$(pg_admin_psql -Atqc \
        "SELECT count(*) FROM pg_hba_file_rules
         WHERE type IN ('host','hostssl') AND address='::1'
           AND auth_method='scram-sha-256'
           AND 'all'=ANY(database) AND 'all'=ANY(user_name)")"
    test "$HBA_SCRAM_IPV6" -ge 1 || fail "No generic SCRAM IPv6 loopback HBA rule is active."
fi
if command -v firewall-cmd >/dev/null 2>&1; then
    for port in 5432 6382 6383 8093 8094; do
        firewall-cmd --quiet --query-port="${port}/tcp" \
            && fail "Private port ${port}/tcp is open in firewalld."
    done
fi

# The legacy stack is an explicit isolation boundary. Record its status but do
# not restart or modify it. Deployment can continue if an operator intentionally
# stopped it; scheduled jobs remain disabled in the new environment either way.
LEGACY_FRONTEND_BEFORE="$(systemctl is-active alessar-frontend.service 2>/dev/null || true)"
LEGACY_DB_BEFORE="$(systemctl is-active alessar-mysql.service 2>/dev/null || true)"

log "Validating and extracting trusted snapshot"
if tar -tzf "$SNAPSHOT_ARCHIVE" | awk '
    /^\// || /(^|\/)\.\.($|\/)/ { bad=1 }
    /(^|\/)\.env$/ || /(^|\/)(backend\.env|admin-credentials|redis-638[23]\.conf)$/ { bad=1 }
    /(^|\/)(id_rsa|id_ed25519)$/ || /\.(pem|key|p12|pfx)$/ { bad=1 }
    END { exit bad }
'; then
    :
else
    fail "Snapshot contains an unsafe path or a secret/key file that must be excluded."
fi
STAGING_DIR="$(mktemp -d /var/tmp/rmwins-stage.XXXXXX)"
tar -xzf "$SNAPSHOT_ARCHIVE" -C "$STAGING_DIR" --no-same-owner --no-same-permissions
chmod 0755 "$STAGING_DIR"
for trusted_file in \
    "$STAGING_DIR/backend/manage.py" \
    "$STAGING_DIR/backend/requirements.txt" \
    "$STAGING_DIR/dist/index.html" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/backend.env.example" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/redis-persistent-6382.conf.example" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/redis-cache-6383.conf.example" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/rmwins-supervisor.service" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/rmwins-frontend.service"; do
    test ! -L "$trusted_file" || fail "Trusted snapshot file must not be a symlink: $trusted_file"
    test -f "$trusted_file" || fail "Snapshot is missing regular file: $trusted_file"
    test "$(stat -c %U "$trusted_file")" = "root" || fail "Staged file is not root-owned: $trusted_file"
done
# Give only root and the app group read/traverse access to the trusted source
# tree. find -P never follows snapshot symlinks; reject links entirely so rsync
# cannot import an unexpected target and no staged secret becomes world-readable.
if find -P "$STAGING_DIR" -mindepth 1 ! -type f ! -type d ! -type l -print -quit | grep -q .; then
    fail "Snapshot contains an unsupported special filesystem entry."
fi
if find -P "$STAGING_DIR" -type l -print -quit | grep -q .; then
    fail "Snapshot must not contain symbolic links."
fi
find -P "$STAGING_DIR" -type d -exec chown root:"$APP_GROUP" {} +
find -P "$STAGING_DIR" -type f -exec chown root:"$APP_GROUP" {} +
find -P "$STAGING_DIR" -type d -exec chmod 0750 {} +
find -P "$STAGING_DIR" -type f -exec chmod 0640 {} +
run_app_clean test -r "$STAGING_DIR/backend/manage.py"
run_app_clean test -r "$STAGING_DIR/dist/index.html"
SNAPSHOT_SHA256="$(sha256sum "$SNAPSHOT_ARCHIVE" | awk '{print $1}')"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_DIR="$BACKUP_ROOT/deploy-$TIMESTAMP-${SNAPSHOT_SHA256:0:12}"
install -d -m 0700 -o root -g root "$BACKUP_DIR"

reject_symlink_or_nondirectory "$APP_DIR"
reject_symlink_or_nondirectory "$FRONTEND_RELEASE"
if test -d "$APP_DIR" && test -n "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit)"; then
    log "Backing up previous application files"
    run_app_clean tar -C "$APP_DIR" \
        --exclude='./.git' \
        --exclude='./backend/.venv' \
        --exclude='./backend/.env' \
        --exclude='./backend/staticfiles' \
        -czf - . > "$BACKUP_DIR/app-before.tar.gz"
    chmod 0600 "$BACKUP_DIR/app-before.tar.gz"
fi
if test -d "$FRONTEND_RELEASE" && test -n "$(find "$FRONTEND_RELEASE" -mindepth 1 -maxdepth 1 -print -quit)"; then
    run_app_clean tar -C "$FRONTEND_RELEASE" -czf - . \
        > "$BACKUP_DIR/frontend-before.tar.gz"
    chmod 0600 "$BACKUP_DIR/frontend-before.tar.gz"
fi
if test -f "$BACKEND_ENV"; then
    install -m 0600 -o root -g root "$BACKEND_ENV" "$BACKUP_DIR/backend.env"
fi

log "Stopping only private RMWins services before code and schema changes"
for unit in rmwins-frontend.service rmwins-supervisor.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl stop "$unit"
    fi
    systemctl is-active --quiet "$unit" \
        && fail "Private unit did not stop cleanly: $unit"
done
# From this point until the final health checks succeed, any failure leaves both
# new private units stopped. This avoids serving mismatched code and schema.
RMWINS_SERVICES_STOPPED=1

log "Creating protected runtime directories"
install -d -m 0755 -o root -g root "$APP_HOME/.config"
install -d -m 0750 -o root -g "$APP_GROUP" "$CONFIG_DIR"
test "$(stat -c '%U:%G:%a' "$APP_HOME/.config")" = "root:root:755" \
    || fail "The .config trust boundary must be root:root mode 0755."
test "$(stat -c '%U:%G:%a' "$CONFIG_DIR")" = "root:$APP_GROUP:750" \
    || fail "The RMWins config directory must be root:$APP_GROUP mode 0750."
run_app_clean mkdir -p "$APP_DIR" "$APP_HOME/app" \
    "$APP_HOME/app/data/redis-persistent" "$APP_HOME/app/data/redis-cache" \
    "$APP_HOME/app/logs/frontend" "$APP_HOME/app/logs/supervisor" \
    "$APP_HOME/app/run/frontend" "$APP_HOME/app/run/supervisor" \
    "$APP_HOME/app/tmp/frontend/client_body" "$APP_HOME/app/tmp/frontend/proxy" \
    "$APP_HOME/app/tmp/frontend/fastcgi" "$APP_HOME/app/tmp/frontend/uwsgi" \
    "$APP_HOME/app/tmp/frontend/scgi"
run_app_clean chmod 0755 "$APP_DIR" "$APP_HOME/app"
run_app_clean chmod 0750 \
    "$APP_HOME/app/data/redis-persistent" "$APP_HOME/app/data/redis-cache" \
    "$APP_HOME/app/logs/frontend" "$APP_HOME/app/logs/supervisor" \
    "$APP_HOME/app/run/frontend" "$APP_HOME/app/run/supervisor" \
    "$APP_HOME/app/tmp/frontend/client_body" "$APP_HOME/app/tmp/frontend/proxy" \
    "$APP_HOME/app/tmp/frontend/fastcgi" "$APP_HOME/app/tmp/frontend/uwsgi" \
    "$APP_HOME/app/tmp/frontend/scgi"

log "Synchronizing snapshot only inside $APP_DIR"
run_app_clean rsync -rlptn --delete --safe-links \
    --exclude='/.git/' \
    --exclude='/dist/' \
    --exclude='/backend/.env' \
    --exclude='/backend/.venv/' \
    --exclude='/backend/staticfiles/' \
    --exclude='**/__pycache__/' \
    --exclude='*.pyc' \
    "$STAGING_DIR/" "$APP_DIR/" >/dev/null
run_app_clean rsync -rlpt --delete --safe-links \
    --exclude='/.git/' \
    --exclude='/dist/' \
    --exclude='/backend/.env' \
    --exclude='/backend/.venv/' \
    --exclude='/backend/staticfiles/' \
    --exclude='**/__pycache__/' \
    --exclude='*.pyc' \
    "$STAGING_DIR/" "$APP_DIR/"

run_app_clean mkdir -p "$FRONTEND_RELEASE"
run_app_clean chmod 0755 "$FRONTEND_RELEASE"
run_app_clean rsync -rlpt --delete --safe-links \
    "$STAGING_DIR/dist/" "$FRONTEND_RELEASE/"

log "Generating first-deploy secrets without printing them"
if test ! -e "$BACKEND_ENV"; then
    run_root_python - "$STAGING_DIR/deploy/rmwins-cyberpanel/backend.env.example" "$BACKEND_ENV" <<'PY'
import os
import secrets
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
replacements = {
    "replace-with-a-long-random-secret": (secrets.token_urlsafe(64), 1),
    "replace-with-a-separate-long-random-secret": (secrets.token_urlsafe(64), 1),
    "replace-with-another-stable-random-secret": (secrets.token_urlsafe(64), 1),
    "replace-with-a-long-random-password": (secrets.token_urlsafe(48), 1),
    "replace-with-a-long-random-database-password": (secrets.token_hex(32), 1),
    "replace-with-a-different-random-database-password": (secrets.token_hex(32), 1),
    # Each Redis instance is referenced by two separate logical-database URLs.
    "replace-with-persistent-redis-password": (secrets.token_urlsafe(48), 2),
    "replace-with-cache-redis-password": (secrets.token_urlsafe(48), 2),
    "replace-with-assigned-supplier-code": ("1000", 1),
}
for old, (new, expected_count) in replacements.items():
    actual_count = text.count(old)
    if actual_count != expected_count:
        raise SystemExit(
            f"Expected {expected_count} occurrence(s) of protected placeholder "
            f"{old}; found {actual_count}"
        )
    text = text.replace(old, new)
unresolved_keys = []
for raw_line in text.splitlines():
    if raw_line and not raw_line.lstrip().startswith("#") and "=" in raw_line:
        key, value = raw_line.split("=", 1)
        if "replace-with-" in value:
            unresolved_keys.append(key)
if unresolved_keys:
    raise SystemExit(f"Unresolved production placeholders in: {sorted(unresolved_keys)}")
fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
PY
fi
reject_symlink_or_nonregular "$BACKEND_ENV"
chmod 0640 "$BACKEND_ENV"
chown root:"$APP_GROUP" "$BACKEND_ENV"

if test ! -e "$REDIS_PERSISTENT_CONFIG" || test ! -e "$REDIS_CACHE_CONFIG"; then
    run_root_python - "$BACKEND_ENV" \
        "$STAGING_DIR/deploy/rmwins-cyberpanel/redis-persistent-6382.conf.example" \
        "$STAGING_DIR/deploy/rmwins-cyberpanel/redis-cache-6383.conf.example" \
        "$REDIS_PERSISTENT_CONFIG" "$REDIS_CACHE_CONFIG" <<'PY'
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

env_path, persistent_source, cache_source, persistent_target, cache_target = map(Path, sys.argv[1:])
values = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    if raw_line and not raw_line.lstrip().startswith("#") and "=" in raw_line:
        key, value = raw_line.split("=", 1)
        values[key] = value
persistent_password = urlparse(values["CELERY_BROKER_URL"]).password
cache_password = urlparse(values["REDIS_CACHE_URL"]).password
if not persistent_password or not cache_password or persistent_password == cache_password:
    raise SystemExit("Redis passwords are missing or not isolated")
for source, target, placeholder, password in (
    (persistent_source, persistent_target, "replace-with-persistent-redis-password", persistent_password),
    (cache_source, cache_target, "replace-with-cache-redis-password", cache_password),
):
    if target.exists():
        continue
    text = source.read_text(encoding="utf-8")
    if text.count(placeholder) != 1:
        raise SystemExit(f"Unexpected Redis template placeholder count in {source}")
    text = text.replace(placeholder, password)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
PY
fi
reject_symlink_or_nonregular "$REDIS_PERSISTENT_CONFIG"
reject_symlink_or_nonregular "$REDIS_CACHE_CONFIG"
chmod 0640 "$REDIS_PERSISTENT_CONFIG" "$REDIS_CACHE_CONFIG"
chown root:"$APP_GROUP" "$REDIS_PERSISTENT_CONFIG" "$REDIS_CACHE_CONFIG"

log "Validating protected environment and Redis isolation"
run_root_python - "$BACKEND_ENV" "$REDIS_PERSISTENT_CONFIG" "$REDIS_CACHE_CONFIG" <<'PY'
import os
import grp
import pwd
import stat
import sys
from pathlib import Path
from urllib.parse import urlparse

env_path, persistent_path, cache_path = map(Path, sys.argv[1:])
values = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    if raw_line and not raw_line.lstrip().startswith("#") and "=" in raw_line:
        key, value = raw_line.split("=", 1)
        if key in values:
            raise SystemExit(f"Duplicate environment key: {key}")
        values[key] = value
expected = {
    "DJANGO_DEBUG": "false",
    "DB_ENGINE": "postgresql",
    "DB_NAME": "rmwins_prod",
    "DB_USER": "rmwins_app",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "PRESCREENER_VAULT_ENABLED": "true",
    "PRESCREENER_DB_ENGINE": "postgresql",
    "PRESCREENER_DB_NAME": "rmwins_vault",
    "PRESCREENER_DB_USER": "rmwins_vault_app",
    "PRESCREENER_DB_HOST": "127.0.0.1",
    "PRESCREENER_DB_PORT": "5432",
    "CACHE_ENABLED": "true",
    "ENABLE_SCHEDULED_JOBS": "false",
}
for key, wanted in expected.items():
    if values.get(key) != wanted:
        raise SystemExit(f"{key} must equal {wanted!r} during private deployment")
for key in (
    "DJANGO_SECRET_KEY", "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
    "RESPONDENT_EMAIL_ENCRYPTION_KEY", "API_DOCS_BASIC_PASSWORD",
    "DB_PASSWORD", "PRESCREENER_DB_PASSWORD",
):
    if len(values.get(key, "")) < 32 or "replace-with-" in values[key]:
        raise SystemExit(f"Missing or weak protected setting: {key}")
if values["DB_NAME"] == values["PRESCREENER_DB_NAME"]:
    raise SystemExit("Operational and vault databases must differ")
if values["DB_USER"] == values["PRESCREENER_DB_USER"]:
    raise SystemExit("Operational and vault database users must differ")
urls = {
    "CELERY_BROKER_URL": (6382, 0),
    "CELERY_RESULT_BACKEND": (6382, 1),
    "REDIS_CACHE_URL": (6383, 0),
    "PROJECTS_REDIS_CACHE_URL": (6383, 1),
}
passwords = {}
for key, (port, database) in urls.items():
    parsed = urlparse(values.get(key, ""))
    if parsed.scheme != "redis" or parsed.hostname != "127.0.0.1" or parsed.port != port:
        raise SystemExit(f"Unexpected private Redis address in {key}")
    if parsed.path != f"/{database}" or not parsed.password:
        raise SystemExit(f"Unexpected Redis database/password in {key}")
    passwords[key] = parsed.password
if passwords["CELERY_BROKER_URL"] != passwords["CELERY_RESULT_BACKEND"]:
    raise SystemExit("Celery Redis passwords do not match")
if passwords["REDIS_CACHE_URL"] != passwords["PROJECTS_REDIS_CACHE_URL"]:
    raise SystemExit("Cache Redis passwords do not match")
if passwords["CELERY_BROKER_URL"] == passwords["REDIS_CACHE_URL"]:
    raise SystemExit("Persistent and cache Redis passwords must differ")
expected_gid = grp.getgrnam("wwwrm1759").gr_gid
for path in (env_path, persistent_path, cache_path):
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise SystemExit(f"Protected path is not a regular file: {path}")
    if stat.S_IMODE(file_stat.st_mode) != 0o640:
        raise SystemExit(f"Protected service file must have exact mode 0640: {path}")
    if file_stat.st_uid != 0 or file_stat.st_gid != expected_gid:
        raise SystemExit(f"Protected service file must be root:wwwrm1759: {path}")
def redis_password(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("requirepass "):
            return line.split(None, 1)[1]
    return ""
if redis_password(persistent_path) != passwords["CELERY_BROKER_URL"]:
    raise SystemExit("Persistent Redis config password differs from backend URL")
if redis_password(cache_path) != passwords["REDIS_CACHE_URL"]:
    raise SystemExit("Cache Redis config password differs from backend URL")
PY

# All mutations below the app-writable backend directory run without root
# privileges. The protected target stays root-owned and group-readable.
run_app_clean "$PYTHON_BIN" - "$BACKEND_DIR/.env" "$BACKEND_ENV" <<'PY'
import os
import stat
import sys
from pathlib import Path

link_path = Path(sys.argv[1])
target = Path(sys.argv[2])
if os.path.lexists(link_path):
    mode = os.lstat(link_path).st_mode
    if stat.S_ISLNK(mode):
        if Path(os.path.realpath(link_path)) != target:
            raise SystemExit("Refusing an unexpected backend/.env symlink")
    elif stat.S_ISREG(mode):
        if link_path.read_bytes() != target.read_bytes():
            raise SystemExit("Refusing to replace an unexpected backend/.env file")
        link_path.unlink()
        link_path.symlink_to(target)
    else:
        raise SystemExit("backend/.env is neither a regular file nor a symlink")
else:
    link_path.symlink_to(target)
PY

DB_NAME="$(env_value DB_NAME)"
DB_USER="$(env_value DB_USER)"
DB_PASSWORD="$(env_value DB_PASSWORD)"
VAULT_DB_NAME="$(env_value PRESCREENER_DB_NAME)"
VAULT_DB_USER="$(env_value PRESCREENER_DB_USER)"
VAULT_DB_PASSWORD="$(env_value PRESCREENER_DB_PASSWORD)"
for identifier in "$DB_NAME" "$DB_USER" "$VAULT_DB_NAME" "$VAULT_DB_USER"; do
    [[ "$identifier" =~ ^[a-z][a-z0-9_]{0,62}$ ]] \
        || fail "PostgreSQL identifier is unsafe: $identifier"
done
test "$DB_NAME" != "$VAULT_DB_NAME" || fail "Database names must differ."
test "$DB_USER" != "$VAULT_DB_USER" || fail "Database users must differ."
test "$DB_NAME:$DB_USER:$VAULT_DB_NAME:$VAULT_DB_USER" = \
    "rmwins_prod:rmwins_app:rmwins_vault:rmwins_vault_app" \
    || fail "Only the dedicated RMWins PostgreSQL identities are allowed."

log "Provisioning dedicated PostgreSQL roles and databases"
PG_SQL="$(mktemp /var/lib/pgsql/.rmwins-provision.XXXXXX.sql)"
TEMP_FILES+=("$PG_SQL")
run_root_python - "$PG_SQL" "$BACKEND_ENV" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
values = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    if raw_line and not raw_line.lstrip().startswith("#") and "=" in raw_line:
        key, value = raw_line.split("=", 1)
        values[key] = value
db_name = values["DB_NAME"]
db_user = values["DB_USER"]
db_password = values["DB_PASSWORD"]
vault_name = values["PRESCREENER_DB_NAME"]
vault_user = values["PRESCREENER_DB_USER"]
vault_password = values["PRESCREENER_DB_PASSWORD"]
def ident(value):
    return '"' + value.replace('"', '""') + '"'
def literal(value):
    return "'" + value.replace("'", "''") + "'"
sql = f"""\
\\set ON_ERROR_STOP on
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_database d
    LEFT JOIN pg_roles r ON r.oid = d.datdba
    WHERE d.datname = {literal(db_name)}
      AND (r.rolname IS DISTINCT FROM {literal(db_user)} OR d.datistemplate OR NOT d.datallowconn
           OR pg_encoding_to_char(d.encoding) <> 'UTF8')
  ) THEN
    RAISE EXCEPTION 'Existing operational database has unexpected provenance';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database d
    LEFT JOIN pg_roles r ON r.oid = d.datdba
    WHERE d.datname = {literal(vault_name)}
      AND (r.rolname IS DISTINCT FROM {literal(vault_user)} OR d.datistemplate OR NOT d.datallowconn
           OR pg_encoding_to_char(d.encoding) <> 'UTF8')
  ) THEN
    RAISE EXCEPTION 'Existing vault database has unexpected provenance';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles r
    WHERE r.rolname IN ({literal(db_user)}, {literal(vault_user)})
      AND (NOT r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
           OR r.rolreplication OR r.rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'Existing RMWins role has unexpected privileges or login state';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles member_role ON member_role.oid = m.member
    JOIN pg_roles granted_role ON granted_role.oid = m.roleid
    WHERE member_role.rolname IN ({literal(db_user)}, {literal(vault_user)})
       OR granted_role.rolname IN ({literal(db_user)}, {literal(vault_user)})
  ) THEN
    RAISE EXCEPTION 'Existing RMWins role has unexpected memberships';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database d
    JOIN pg_roles r ON r.oid = d.datdba
    WHERE (r.rolname = {literal(db_user)} AND d.datname <> {literal(db_name)})
       OR (r.rolname = {literal(vault_user)} AND d.datname <> {literal(vault_name)})
  ) THEN
    RAISE EXCEPTION 'Existing RMWins role owns an unexpected database';
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(db_user)}) THEN
    CREATE ROLE {ident(db_user)} LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(vault_user)}) THEN
    CREATE ROLE {ident(vault_user)} LOGIN;
  END IF;
END $$;
ALTER ROLE {ident(db_user)} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT PASSWORD {literal(db_password)};
ALTER ROLE {ident(vault_user)} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT PASSWORD {literal(vault_password)};
REVOKE {ident(db_user)} FROM {ident(vault_user)};
REVOKE {ident(vault_user)} FROM {ident(db_user)};
SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0', {literal(db_name)}, {literal(db_user)})
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {literal(db_name)})\\gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0', {literal(vault_name)}, {literal(vault_user)})
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {literal(vault_name)})\\gexec
ALTER DATABASE {ident(db_name)} OWNER TO {ident(db_user)};
ALTER DATABASE {ident(vault_name)} OWNER TO {ident(vault_user)};
REVOKE ALL ON DATABASE {ident(db_name)} FROM PUBLIC;
REVOKE ALL ON DATABASE {ident(vault_name)} FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE {ident(db_name)} FROM {ident(vault_user)};
REVOKE CONNECT, TEMPORARY ON DATABASE {ident(vault_name)} FROM {ident(db_user)};
GRANT CONNECT, TEMPORARY ON DATABASE {ident(db_name)} TO {ident(db_user)};
GRANT CONNECT, TEMPORARY ON DATABASE {ident(vault_name)} TO {ident(vault_user)};
\\connect {ident(db_name)}
ALTER SCHEMA public OWNER TO {ident(db_user)};
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO {ident(db_user)};
\\connect {ident(vault_name)}
ALTER SCHEMA public OWNER TO {ident(vault_user)};
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO {ident(vault_user)};
"""
path.write_text(sql, encoding="utf-8")
os.chmod(path, 0o600)
PY
chown postgres:postgres "$PG_SQL"
pg_admin_psql --file="$PG_SQL" >/dev/null
rm -f -- "$PG_SQL"
TEMP_FILES=()

log "Backing up PostgreSQL before migrations"
pg_admin_dump "$DB_NAME" > "$BACKUP_DIR/$DB_NAME.dump"
pg_admin_dump "$VAULT_DB_NAME" > "$BACKUP_DIR/$VAULT_DB_NAME.dump"
chmod 0600 "$BACKUP_DIR/$DB_NAME.dump" "$BACKUP_DIR/$VAULT_DB_NAME.dump"
chown root:root "$BACKUP_DIR/$DB_NAME.dump" "$BACKUP_DIR/$VAULT_DB_NAME.dump"

log "Installing backend dependencies and applying both database migrations"
if test ! -x "$VENV_DIR/bin/python"; then
    run_app_clean "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
run_app_clean \
    "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$BACKEND_DIR/requirements.txt"
run_app_clean bash --noprofile --norc -c "
    set -Eeuo pipefail
    cd '$BACKEND_DIR'
    '$VENV_DIR/bin/python' manage.py migrate --noinput
    '$VENV_DIR/bin/python' manage.py migrate --database=prescreener_vault --noinput
    '$VENV_DIR/bin/python' manage.py collectstatic --noinput
    '$VENV_DIR/bin/python' manage.py check --deploy
"

log "Ensuring a private administrator exists without changing established admins"
ADMIN_STATE="$(run_app_clean env DJANGO_SETTINGS_MODULE=config.settings \
    PYTHONPATH="$BACKEND_DIR" "$VENV_DIR/bin/python" -c '
import django
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
print(f"{User.objects.count()}:{User.objects.filter(is_active=True, is_staff=True, is_superuser=True).count()}")
')"
ADMIN_TOTAL_USERS="${ADMIN_STATE%%:*}"
ADMIN_ACTIVE_SUPERUSERS="${ADMIN_STATE##*:}"
[[ "$ADMIN_TOTAL_USERS" =~ ^[0-9]+$ && "$ADMIN_ACTIVE_SUPERUSERS" =~ ^[0-9]+$ ]] \
    || fail "Could not determine the administrator state safely."

if test "$ADMIN_ACTIVE_SUPERUSERS" -gt 0; then
    log "An active Django superuser already exists; leaving every administrator unchanged"
elif test "$ADMIN_TOTAL_USERS" -gt 0; then
    fail "Users exist but no active Django superuser is available; recover one manually."
else
    ADMIN_TEMP=""
    if test ! -e "$ADMIN_CREDENTIALS"; then
        ADMIN_TEMP="$(mktemp "$CONFIG_DIR/.admin-credentials.XXXXXX")"
        TEMP_FILES+=("$ADMIN_TEMP")
        {
            printf 'username=rmwins_admin\npassword='
            openssl rand -hex 24
            printf 'created_at=%s\n' "$(date --iso-8601=seconds)"
        } > "$ADMIN_TEMP"
        chmod 0600 "$ADMIN_TEMP"
        chown root:root "$ADMIN_TEMP"
        ADMIN_CREDENTIAL_SOURCE="$ADMIN_TEMP"
    else
        reject_symlink_or_nonregular "$ADMIN_CREDENTIALS"
        test "$(stat -c '%U:%G:%a' "$ADMIN_CREDENTIALS")" = "root:root:600" \
            || fail "Administrator credentials must be root:root mode 0600."
        ADMIN_CREDENTIAL_SOURCE="$ADMIN_CREDENTIALS"
    fi
    if run_root_python -c '
import sys
from pathlib import Path
values = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        if key in values:
            raise SystemExit("Duplicate administrator credential key")
        values[key] = value
if values.get("username") != "rmwins_admin" or len(values.get("password", "")) < 32:
    raise SystemExit("Invalid protected administrator credential file")
print(values["password"])
' "$ADMIN_CREDENTIAL_SOURCE" | \
    run_app_clean env ADMIN_USERNAME=rmwins_admin ADMIN_EMAIL=rmwins-admin@localhost.invalid \
    "$VENV_DIR/bin/python" "$BACKEND_DIR/manage.py" shell -c '
import os
import sys
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ["ADMIN_USERNAME"]
password = sys.stdin.readline().rstrip("\n")
if len(password) < 32:
    raise SystemExit("Administrator password was not received securely")
user = User.objects.filter(username=username).first()
if user is None:
    User.objects.create_superuser(username=username, email=os.environ["ADMIN_EMAIL"], password=password)
else:
    raise SystemExit("Refusing to overwrite an existing bootstrap username")
' >/dev/null; then
        if test -n "$ADMIN_TEMP"; then
            mv "$ADMIN_TEMP" "$ADMIN_CREDENTIALS"
            TEMP_FILES=()
        fi
    else
        fail "Private administrator bootstrap failed."
    fi
fi
if test -e "$ADMIN_CREDENTIALS"; then
    reject_symlink_or_nonregular "$ADMIN_CREDENTIALS"
    chmod 0600 "$ADMIN_CREDENTIALS"
    chown root:root "$ADMIN_CREDENTIALS"
fi

log "Validating private service configurations"
# Redis 6 has no parse-only config flag. Run its standalone memory test here;
# each protected config is then exercised by controlled systemd startup and an
# authenticated PING before deployment can succeed.
run_app_clean /usr/bin/redis-server --test-memory 2 >/dev/null
run_app_clean /usr/sbin/nginx -t -e stderr \
    -c "$APP_DIR/deploy/rmwins-cyberpanel/frontend-nginx.conf"
run_app_clean "$VENV_DIR/bin/python" - "$SUPERVISOR_CONFIG" <<'PY'
import configparser
import sys
parser = configparser.RawConfigParser(strict=True)
with open(sys.argv[1], encoding="utf-8") as handle:
    parser.read_file(handle)
required = {
    "program:rmwins-redis-persistent", "program:rmwins-redis-cache",
    "program:rmwins-web", "program:rmwins-worker", "program:rmwins-beat",
}
missing = sorted(required.difference(parser.sections()))
if missing:
    raise SystemExit(f"Missing Supervisor sections: {missing}")
PY

log "Installing and starting private-only systemd services"
systemd-analyze verify \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/rmwins-supervisor.service" \
    "$STAGING_DIR/deploy/rmwins-cyberpanel/rmwins-frontend.service"
for unit in rmwins-supervisor.service rmwins-frontend.service; do
    # Root systemd definitions must come directly from the immutable,
    # root-owned staging tree, never from the app-user-writable checkout.
    source_unit="$STAGING_DIR/deploy/rmwins-cyberpanel/$unit"
    target_unit="/etc/systemd/system/$unit"
    test ! -L "$source_unit" || fail "Unit source must not be a symlink: $source_unit"
    test -f "$source_unit" || fail "Missing regular unit: $source_unit"
    test "$(stat -c %U "$source_unit")" = "root" || fail "Unit source must be root-owned."
    if test -f "$target_unit" && ! cmp -s "$source_unit" "$target_unit"; then
        install -m 0600 "$target_unit" "$BACKUP_DIR/$unit.before"
    fi
    install -m 0644 "$source_unit" "$target_unit"
done
systemctl daemon-reload
systemctl enable rmwins-supervisor.service rmwins-frontend.service >/dev/null
restart_or_start rmwins-supervisor.service
restart_or_start rmwins-frontend.service
sleep 8

log "Running private health checks"
systemctl is-active --quiet rmwins-supervisor.service || fail "RMWins Supervisor service is inactive."
systemctl is-active --quiet rmwins-frontend.service || fail "RMWins frontend service is inactive."

redis_password_from_env() {
    run_root_python - "$BACKEND_ENV" "$1" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlparse

env_path = Path(sys.argv[1])
wanted_key = sys.argv[2]
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    if raw_line.startswith(f"{wanted_key}="):
        password = urlparse(raw_line.split("=", 1)[1]).password
        if not password:
            raise SystemExit(f"Missing password in {wanted_key}")
        print(password)
        break
else:
    raise SystemExit(f"Missing environment key: {wanted_key}")
PY
}
REDIS_PERSISTENT_PASSWORD="$(redis_password_from_env CELERY_BROKER_URL)"
REDIS_CACHE_PASSWORD="$(redis_password_from_env REDIS_CACHE_URL)"
REDISCLI_AUTH="$REDIS_PERSISTENT_PASSWORD" redis-cli -h 127.0.0.1 -p 6382 ping | grep -Fxq PONG \
    || fail "Persistent Redis health check failed."
REDISCLI_AUTH="$REDIS_CACHE_PASSWORD" redis-cli -h 127.0.0.1 -p 6383 ping | grep -Fxq PONG \
    || fail "Cache Redis health check failed."
REDISCLI_AUTH="$REDIS_CACHE_PASSWORD" redis-cli -h 127.0.0.1 -p 6383 FLUSHALL >/dev/null
unset REDIS_PERSISTENT_PASSWORD REDIS_CACHE_PASSWORD

pg_password_psql "$DB_PASSWORD" -h 127.0.0.1 -p 5432 -U "$DB_USER" -d "$DB_NAME" -Atqc 'SELECT 1' | grep -Fxq 1 \
    || fail "Operational PostgreSQL login failed."
pg_password_psql "$VAULT_DB_PASSWORD" -h 127.0.0.1 -p 5432 -U "$VAULT_DB_USER" -d "$VAULT_DB_NAME" -Atqc 'SELECT 1' | grep -Fxq 1 \
    || fail "Vault PostgreSQL login failed."

# Negative authentication/isolation proofs: TCP must enforce SCRAM passwords,
# and neither application role may connect to the other role's database.
WRONG_DB_PASSWORD="$(openssl rand -hex 32)"
if pg_password_psql "$WRONG_DB_PASSWORD" -h 127.0.0.1 -p 5432 \
    -U "$DB_USER" -d "$DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
    fail "Operational PostgreSQL unexpectedly accepted a deliberately wrong password."
fi
if pg_password_psql "$WRONG_DB_PASSWORD" -h 127.0.0.1 -p 5432 \
    -U "$VAULT_DB_USER" -d "$VAULT_DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
    fail "Vault PostgreSQL unexpectedly accepted a deliberately wrong password."
fi
if printf '%s\n' "$PG_LISTENERS" | grep -Fxq '[::1]:5432'; then
    if pg_password_psql "$WRONG_DB_PASSWORD" -h ::1 -p 5432 \
        -U "$DB_USER" -d "$DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
        fail "Operational PostgreSQL accepted a wrong password over IPv6 loopback."
    fi
    if pg_password_psql "$WRONG_DB_PASSWORD" -h ::1 -p 5432 \
        -U "$VAULT_DB_USER" -d "$VAULT_DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
        fail "Vault PostgreSQL accepted a wrong password over IPv6 loopback."
    fi
fi
unset WRONG_DB_PASSWORD
if pg_password_psql "$DB_PASSWORD" -h 127.0.0.1 -p 5432 \
    -U "$DB_USER" -d "$VAULT_DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
    fail "Operational role unexpectedly connected to the vault database."
fi
if pg_password_psql "$VAULT_DB_PASSWORD" -h 127.0.0.1 -p 5432 \
    -U "$VAULT_DB_USER" -d "$DB_NAME" -Atqc 'SELECT 1' >/dev/null 2>&1; then
    fail "Vault role unexpectedly connected to the operational database."
fi
unset DB_PASSWORD VAULT_DB_PASSWORD

curl --fail --silent --show-error --max-time 20 http://127.0.0.1:8094/__health | grep -Fxq ok \
    || fail "Frontend private health check failed."
curl --fail --silent --show-error --max-time 20 \
    -H 'Host: api.rmwinsights.com' -H 'X-Forwarded-Proto: https' \
    http://127.0.0.1:8093/api/v1/auth/session/ >/dev/null \
    || fail "Backend private auth-session health check failed."

SUPERVISOR_STATUS="$(run_app_clean "$SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status)"
printf '%s\n' "$SUPERVISOR_STATUS"
if printf '%s\n' "$SUPERVISOR_STATUS" | awk '$2 != "RUNNING" { bad=1 } END { exit bad }'; then
    :
else
    fail "One or more private Supervisor programs are not RUNNING."
fi

for port in 5432 6382 6383 8093 8094; do
    ss -H -ltn | awk '{print $4}' | grep -Eq "127\.0\.0\.1:${port}$" \
        || fail "Expected IPv4 loopback listener is missing on port $port."
done
if ss -H -ltn | awk '$4 ~ /:(6382|6383|8093|8094)$/ {print $4}' \
    | grep -Ev '^127\.0\.0\.1:(6382|6383|8093|8094)$' | grep -q .; then
    fail "An RMWins private service has a non-loopback listener."
fi

LEGACY_FRONTEND_AFTER="$(systemctl is-active alessar-frontend.service 2>/dev/null || true)"
LEGACY_DB_AFTER="$(systemctl is-active alessar-mysql.service 2>/dev/null || true)"
test "$LEGACY_FRONTEND_AFTER" = "$LEGACY_FRONTEND_BEFORE" \
    || fail "Legacy Alessar frontend state changed unexpectedly."
test "$LEGACY_DB_AFTER" = "$LEGACY_DB_BEFORE" \
    || fail "Legacy Alessar database state changed unexpectedly."

RMWINS_SERVICES_STOPPED=0
printf '%s\n' "$SNAPSHOT_SHA256" > "$STATE_DIR/last_snapshot_sha256"
printf '%s\n' "$(date --iso-8601=seconds)" > "$STATE_DIR/last_private_deploy_at"
chmod 0600 "$STATE_DIR/last_snapshot_sha256" "$STATE_DIR/last_private_deploy_at"

log "PRIVATE DEPLOY SUCCESS"
printf 'Snapshot: %s\n' "$SNAPSHOT_SHA256"
printf 'Backend:  http://127.0.0.1:8093 (healthy)\n'
printf 'Frontend: http://127.0.0.1:8094 (healthy)\n'
printf 'Redis:    127.0.0.1:6382 persistent, 127.0.0.1:6383 cache\n'
printf 'Postgres: 127.0.0.1:5432, two isolated roles/databases\n'
printf 'Admin credentials: %s (0600; password was not printed)\n' "$ADMIN_CREDENTIALS"
printf 'Public Nginx/DNS/TLS: unchanged\n'
