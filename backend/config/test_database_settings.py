"""Focused tests for environment-driven operational database selection."""

import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .settings import (
    _operational_database_from_env,
    _prescreener_database_from_env,
    _validate_prescreener_database_isolation,
)


class OperationalDatabaseSettingsTests(SimpleTestCase):
    def test_postgresql_engine_and_connection_options_are_read_from_environment(self):
        environment = {
            "DB_ENGINE": "postgresql",
            "DB_NAME": "rmwins",
            "DB_USER": "rmwins_app",
            "DB_PASSWORD": "database-secret",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_CONN_MAX_AGE": "120",
            "DB_CONN_HEALTH_CHECKS": "true",
            "DB_CONNECT_TIMEOUT": "7",
            "DB_SSLMODE": "require",
        }

        with patch.dict(os.environ, environment):
            engine, database = _operational_database_from_env()

        self.assertEqual(engine, "postgresql")
        self.assertEqual(database, {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "rmwins",
            "USER": "rmwins_app",
            "PASSWORD": "database-secret",
            "HOST": "127.0.0.1",
            "PORT": "5432",
            "CONN_MAX_AGE": 120,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {"connect_timeout": 7, "sslmode": "require"},
        })

    def test_postgres_alias_uses_postgresql_backend_without_forcing_ssl(self):
        with patch.dict(os.environ, {
            "DB_ENGINE": "postgres",
            "DB_SSLMODE": "",
        }):
            engine, database = _operational_database_from_env()

        self.assertEqual(engine, "postgres")
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        self.assertNotIn("sslmode", database["OPTIONS"])

    def test_unknown_engine_fails_closed_instead_of_creating_sqlite(self):
        with patch.dict(os.environ, {"DB_ENGINE": "postgress"}):
            with self.assertRaisesRegex(ImproperlyConfigured, "Unsupported DB_ENGINE"):
                _operational_database_from_env()


class PrescreenerDatabaseSettingsTests(SimpleTestCase):
    def test_postgresql_vault_uses_its_own_credentials_and_connection_reuse(self):
        environment = {
            "PRESCREENER_DB_ENGINE": "postgresql",
            "PRESCREENER_DB_NAME": "rmwins_vault",
            "PRESCREENER_DB_USER": "rmwins_vault_app",
            "PRESCREENER_DB_PASSWORD": "separate-vault-secret",
            "PRESCREENER_DB_HOST": "127.0.0.1",
            "PRESCREENER_DB_PORT": "5432",
            "PRESCREENER_DB_CONN_MAX_AGE": "120",
            "PRESCREENER_DB_CONN_HEALTH_CHECKS": "true",
            "PRESCREENER_DB_CONNECT_TIMEOUT": "8",
            "PRESCREENER_DB_SSLMODE": "require",
        }

        with patch.dict(os.environ, environment):
            engine, database = _prescreener_database_from_env()

        self.assertEqual(engine, "postgresql")
        self.assertEqual(database, {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "rmwins_vault",
            "USER": "rmwins_vault_app",
            "PASSWORD": "separate-vault-secret",
            "HOST": "127.0.0.1",
            "PORT": "5432",
            "CONN_MAX_AGE": 120,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {"connect_timeout": 8, "sslmode": "require"},
        })

    def test_postgres_alias_does_not_force_vault_tls(self):
        with patch.dict(os.environ, {
            "PRESCREENER_DB_ENGINE": "postgres",
            "PRESCREENER_DB_SSLMODE": "",
        }):
            engine, database = _prescreener_database_from_env()

        self.assertEqual(engine, "postgres")
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        self.assertNotIn("sslmode", database["OPTIONS"])

    def test_unknown_vault_engine_fails_closed(self):
        with patch.dict(
            os.environ, {"PRESCREENER_DB_ENGINE": "postgress"}
        ):
            with self.assertRaisesRegex(
                ImproperlyConfigured, "Unsupported PRESCREENER_DB_ENGINE"
            ):
                _prescreener_database_from_env()

    def test_enabled_vault_requires_separate_database_and_user(self):
        operational = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "rmwins",
            "USER": "rmwins_app",
            "HOST": "127.0.0.1",
            "PORT": "5432",
        }
        same_database = {
            **operational,
            "USER": "rmwins_vault_app",
        }
        with self.assertRaisesRegex(ImproperlyConfigured, "database name"):
            _validate_prescreener_database_isolation(
                True, operational, same_database
            )

        reused_user = {
            **operational,
            "NAME": "rmwins_vault",
        }
        with self.assertRaisesRegex(ImproperlyConfigured, "database user"):
            _validate_prescreener_database_isolation(
                True, operational, reused_user
            )
