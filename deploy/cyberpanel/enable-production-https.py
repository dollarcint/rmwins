#!/usr/bin/env python3
"""Atomically enable Django HTTPS enforcement without exposing environment secrets."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run as root.")
    if len(sys.argv) != 2:
        raise SystemExit("Usage: enable-production-https.py /absolute/path/to/.env")

    env_path = Path(sys.argv[1])
    original = env_path.read_text(encoding="utf-8")
    replacements = {
        "DJANGO_SECURE_SSL_REDIRECT=false": "DJANGO_SECURE_SSL_REDIRECT=true",
        "DJANGO_SECURE_HSTS_SECONDS=0": "DJANGO_SECURE_HSTS_SECONDS=31536000",
    }
    updated = original
    for old, new in replacements.items():
        if updated.count(old) != 1:
            raise SystemExit(f"Expected exactly one {old!r} setting; refusing to edit.")
        updated = updated.replace(old, new)

    current_stat = env_path.stat()
    temp_path = env_path.with_name(f".{env_path.name}.{secrets.token_hex(8)}.tmp")
    temp_path.write_text(updated, encoding="utf-8")
    os.chmod(temp_path, current_stat.st_mode & 0o777)
    os.chown(temp_path, current_stat.st_uid, current_stat.st_gid)
    temp_path.replace(env_path)
    print("Django HTTPS redirect and one-year HSTS enabled.")


if __name__ == "__main__":
    main()
