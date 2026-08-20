"""Regression tests for PostgreSQL-only ordered-index migration guards."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase


SURVEY_MIGRATION = import_module(
    "surveys.migrations.0026_postgresql_hot_path_indexes"
)
VAULT_MIGRATION = import_module(
    "prescreener_vault.migrations.0008_prescreener_candidate_queue_index"
)


def schema_editor(*, vendor, alias):
    return SimpleNamespace(
        connection=SimpleNamespace(vendor=vendor, alias=alias),
        quote_name=lambda value: f'"{value}"',
        execute=Mock(),
    )


class PostgreSQLOrderedIndexMigrationTests(SimpleTestCase):
    def test_survey_indexes_are_ordered_and_partial_on_operational_postgres(self):
        editor = schema_editor(vendor="postgresql", alias="default")

        SURVEY_MIGRATION.create_postgresql_ordered_indexes(None, editor)

        self.assertEqual(editor.execute.call_count, 2)
        detail_sql = editor.execute.call_args_list[0].args[0]
        reconcile_sql = editor.execute.call_args_list[1].args[0]
        self.assertIn('"detail_synced_at" ASC NULLS FIRST', detail_sql)
        self.assertIn('"source_modified_at" DESC NULLS LAST', detail_sql)
        self.assertIn('"upstream_checked_at" ASC NULLS FIRST', reconcile_sql)
        self.assertIn('WHERE "status" = \'redirected\'', reconcile_sql)
        self.assertIn('"callback_at" IS NULL', reconcile_sql)

    def test_survey_indexes_skip_sqlite_and_the_vault_alias(self):
        for vendor, alias in (
            ("sqlite", "default"),
            ("postgresql", "prescreener_vault"),
        ):
            editor = schema_editor(vendor=vendor, alias=alias)
            SURVEY_MIGRATION.create_postgresql_ordered_indexes(None, editor)
            SURVEY_MIGRATION.drop_postgresql_ordered_indexes(None, editor)
            editor.execute.assert_not_called()

    def test_vault_index_runs_only_on_the_postgresql_vault_alias(self):
        editor = schema_editor(
            vendor="postgresql", alias="prescreener_vault"
        )

        VAULT_MIGRATION.create_postgresql_candidate_index(None, editor)

        sql = editor.execute.call_args.args[0]
        self.assertIn('"last_reused_at" ASC NULLS FIRST', sql)
        self.assertIn('"vault_candidate_queue_idx"', sql)

        skipped = schema_editor(vendor="postgresql", alias="default")
        VAULT_MIGRATION.create_postgresql_candidate_index(None, skipped)
        VAULT_MIGRATION.drop_postgresql_candidate_index(None, skipped)
        skipped.execute.assert_not_called()
