from django.db import migrations, models


def create_postgresql_candidate_index(apps, schema_editor):
    if (
        schema_editor.connection.vendor != "postgresql"
        or schema_editor.connection.alias != "prescreener_vault"
    ):
        return
    quote = schema_editor.quote_name
    schema_editor.execute(
        f"CREATE INDEX {quote('vault_candidate_queue_idx')} "
        f"ON {quote('prescreener_vault_prescreenersubmission')} ("
        f"{quote('source_client_code')}, {quote('country_code')}, "
        f"{quote('respondent_gender')}, {quote('usage_count')}, "
        f"{quote('last_reused_at')} ASC NULLS FIRST, "
        f"{quote('submitted_at')}, {quote('uid')})"
    )


def drop_postgresql_candidate_index(apps, schema_editor):
    if (
        schema_editor.connection.vendor != "postgresql"
        or schema_editor.connection.alias != "prescreener_vault"
    ):
        return
    schema_editor.execute(
        f"DROP INDEX IF EXISTS {schema_editor.quote_name('vault_candidate_queue_idx')}"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("prescreener_vault", "0007_prescreenersubmission_vault_reuse_age_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    create_postgresql_candidate_index,
                    drop_postgresql_candidate_index,
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="prescreenersubmission",
                    index=models.Index(
                        models.F("source_client_code"),
                        models.F("country_code"),
                        models.F("respondent_gender"),
                        models.F("usage_count"),
                        models.OrderBy(
                            models.F("last_reused_at"), nulls_first=True
                        ),
                        models.F("submitted_at"),
                        models.F("uid"),
                        name="vault_candidate_queue_idx",
                    ),
                ),
            ],
        ),
    ]
