#!/usr/bin/env python3
"""Provision an isolated Alessar MySQL database and production environment."""

from __future__ import annotations

import argparse
import ast
import os
import pwd
import secrets
import subprocess
from pathlib import Path


DB_NAME = "alessar_prod"
DB_USER = "alessar_app"
APP_USER = "apial8464"
MYSQL_SOCKET = Path("/home/api.alessarsolutions.in/tmp/alessar-mysql.sock")


def read_dotenv_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            try:
                value = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                value = value[1:-1]
        return value
    return ""


def run_mysql(user: str, password: str, sql: str, *, check: bool, capture: bool) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password
    else:
        env.pop("MYSQL_PWD", None)
    return subprocess.run(
        [
            "mysql",
            "--batch",
            "--skip-column-names",
            "--protocol=socket",
            f"--socket={MYSQL_SOCKET}",
            f"--user={user}",
        ],
        input=sql,
        text=True,
        env=env,
        check=check,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def mysql_admin_credentials() -> tuple[str, str]:
    if not MYSQL_SOCKET.exists():
        raise RuntimeError(f"Isolated Alessar MySQL socket is unavailable: {MYSQL_SOCKET}")
    probe = run_mysql("root", "", "SHOW GRANTS FOR CURRENT_USER;", check=False, capture=True)
    if probe.returncode != 0 or "ALL PRIVILEGES ON *.*" not in probe.stdout.upper():
        raise RuntimeError("The isolated Alessar MySQL root socket login is not available.")
    print("Using the isolated Alessar MySQL root socket.")
    return "root", ""


def mysql(sql: str, *, capture: bool = False) -> str:
    mysql_user, mysql_password = mysql_admin_credentials()
    completed = run_mysql(mysql_user, mysql_password, sql, check=True, capture=capture)
    return completed.stdout.strip() if capture else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_env", type=Path)
    parser.add_argument("destination_env", type=Path)
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Run this provisioner as root.")
    if args.destination_env.exists():
        raise SystemExit(f"Refusing to overwrite existing {args.destination_env}")
    if not args.source_env.is_file():
        raise SystemExit(f"Missing source environment: {args.source_env}")
    if not MYSQL_SOCKET.exists():
        raise SystemExit(f"Missing isolated Alessar MySQL socket: {MYSQL_SOCKET}")

    token = read_dotenv_value(args.source_env, "INNOVATEMR_API_TOKEN")
    if not token:
        raise SystemExit("INNOVATEMR_API_TOKEN is missing or empty in source environment.")

    existing = mysql(
        "SELECT CONCAT('db:', SCHEMA_NAME) FROM INFORMATION_SCHEMA.SCHEMATA "
        f"WHERE SCHEMA_NAME='{DB_NAME}';"
        "SELECT CONCAT('user:', User, '@', Host) FROM mysql.user "
        f"WHERE User='{DB_USER}';",
        capture=True,
    )
    if existing:
        raise SystemExit(f"Refusing to modify an existing Alessar DB identity: {existing}")

    db_password = secrets.token_hex(32)
    django_secret = secrets.token_urlsafe(64)
    sql = f"""
CREATE DATABASE `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '{DB_USER}'@'127.0.0.1' IDENTIFIED BY '{db_password}';
CREATE USER '{DB_USER}'@'localhost' IDENTIFIED BY '{db_password}';
GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO '{DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO '{DB_USER}'@'localhost';
FLUSH PRIVILEGES;
"""
    mysql(sql)

    values = {
        "DJANGO_SECRET_KEY": django_secret,
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "api.alessarsolutions.in,127.0.0.1,localhost",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://api.alessarsolutions.in,https://alessarsolutions.in,https://www.alessarsolutions.in",
        "DJANGO_CORS_ALLOWED_ORIGINS": "https://alessarsolutions.in,https://www.alessarsolutions.in",
        "DJANGO_BEHIND_HTTPS_PROXY": "true",
        "DJANGO_SECURE_SSL_REDIRECT": "false",
        "DJANGO_SESSION_COOKIE_SECURE": "true",
        "DJANGO_CSRF_COOKIE_SECURE": "true",
        "DJANGO_SECURE_HSTS_SECONDS": "0",
        "TRUST_X_FORWARDED_FOR": "true",
        "DB_ENGINE": "mysql",
        "DB_NAME": DB_NAME,
        "DB_USER": DB_USER,
        "DB_PASSWORD": db_password,
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3307",
        "DB_CONN_MAX_AGE": "60",
        "DB_CONNECT_TIMEOUT": "10",
        "INNOVATEMR_API_TOKEN": token,
        "INNOVATEMR_BASE_URL": "https://supplier.innovatemr.net/api/v2",
        "PUBLIC_SUPPLIER_CODE": "508",
        "INNOVATEMR_TIMEOUT_SECONDS": "30",
        "INNOVATEMR_PAGE_SIZE": "100",
        "INNOVATEMR_MAX_PAGES": "1000",
        "INNOVATEMR_DETAIL_REFRESH_BATCH": "20",
        "INNOVATEMR_INVENTORY_SYNC_INTERVAL_SECONDS": "150",
        "INNOVATEMR_DETAIL_SYNC_INTERVAL_SECONDS": "150",
        "INNOVATEMR_ATTEMPT_RECONCILE_INTERVAL_SECONDS": "60",
        "INNOVATEMR_ATTEMPT_RECONCILE_BATCH": "20",
        "INNOVATEMR_ATTEMPT_RECONCILE_LOOKBACK_HOURS": "168",
        "CELERY_BROKER_URL": "redis://127.0.0.1:6381/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6381/1",
        "ENABLE_SCHEDULED_JOBS": "true",
        "VENDOR_RESERVATION_TTL_MINUTES": "180",
        "VENDOR_RESERVATION_CLEANUP_INTERVAL_SECONDS": "60",
    }

    args.destination_env.parent.mkdir(parents=True, exist_ok=True)
    temp_env = args.destination_env.with_name(f".{args.destination_env.name}.{secrets.token_hex(8)}.tmp")
    temp_env.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    os.chmod(temp_env, 0o600)
    account = pwd.getpwnam(APP_USER)
    os.chown(temp_env, account.pw_uid, account.pw_gid)
    temp_env.replace(args.destination_env)
    args.source_env.unlink()

    print(f"Created isolated database {DB_NAME} and user {DB_USER}.")
    print(f"Wrote protected production environment to {args.destination_env}.")


if __name__ == "__main__":
    main()
