#!/usr/bin/env python3
"""Print non-secret Alessar deployment health facts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from surveys.models import Survey  # noqa: E402


links = list(Survey.objects.exclude(entry_link="").values_list("entry_link", flat=True))
supplier_matches = 0
for link in links:
    code = parse_qs(urlparse(link).query).get("supCode", [])
    if settings.PUBLIC_SUPPLIER_CODE in code:
        supplier_matches += 1

print(f"database={settings.DATABASES['default']['NAME']}:{settings.DATABASES['default']['PORT']}")
print(f"surveys={Survey.objects.count()}")
print(f"entry_links={len(links)}")
print(f"supplier_code={settings.PUBLIC_SUPPLIER_CODE}")
print(f"matching_supplier_links={supplier_matches}")
print(f"superusers={get_user_model().objects.filter(is_superuser=True).count()}")
