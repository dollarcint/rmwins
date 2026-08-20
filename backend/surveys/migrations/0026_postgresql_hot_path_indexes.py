from django.db import migrations, models


def create_postgresql_ordered_indexes(apps, schema_editor):
    if (
        schema_editor.connection.vendor != "postgresql"
        or schema_editor.connection.alias != "default"
    ):
        return
    quote = schema_editor.quote_name
    schema_editor.execute(
        f"CREATE INDEX {quote('survey_sync_detail_idx')} "
        f"ON {quote('surveys_survey')} ("
        f"{quote('integration_id')}, {quote('status')}, "
        f"{quote('detail_synced_at')} ASC NULLS FIRST, "
        f"{quote('source_modified_at')} DESC NULLS LAST)"
    )
    schema_editor.execute(
        f"CREATE INDEX {quote('attempt_reconcile_idx')} "
        f"ON {quote('surveys_surveyattempt')} ("
        f"{quote('upstream_checked_at')} ASC NULLS FIRST, "
        f"{quote('initiated_at')} DESC) "
        f"WHERE {quote('status')} = 'redirected' "
        f"AND {quote('callback_at')} IS NULL"
    )


def drop_postgresql_ordered_indexes(apps, schema_editor):
    if (
        schema_editor.connection.vendor != "postgresql"
        or schema_editor.connection.alias != "default"
    ):
        return
    quote = schema_editor.quote_name
    schema_editor.execute(
        f"DROP INDEX IF EXISTS {quote('attempt_reconcile_idx')}"
    )
    schema_editor.execute(
        f"DROP INDEX IF EXISTS {quote('survey_sync_detail_idx')}"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0025_profilereuseprojectusage_profilereusestate_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="survey",
            options={
                "ordering": [
                    models.OrderBy(
                        models.F("source_modified_at"),
                        descending=True,
                        nulls_last=True,
                    ),
                    models.OrderBy(
                        models.F("created_at"), descending=True
                    ),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="surveyattempt",
            index=models.Index(
                fields=["platform_user", "-initiated_at"],
                name="attempt_user_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="surveyattempt",
            index=models.Index(
                fields=["survey", "status"],
                name="attempt_survey_status_idx",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    create_postgresql_ordered_indexes,
                    drop_postgresql_ordered_indexes,
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="survey",
                    index=models.Index(
                        models.F("integration"),
                        models.F("status"),
                        models.OrderBy(
                            models.F("detail_synced_at"), nulls_first=True
                        ),
                        models.OrderBy(
                            models.F("source_modified_at"),
                            descending=True,
                            nulls_last=True,
                        ),
                        name="survey_sync_detail_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="surveyattempt",
                    index=models.Index(
                        models.OrderBy(
                            models.F("upstream_checked_at"), nulls_first=True
                        ),
                        models.OrderBy(
                            models.F("initiated_at"), descending=True
                        ),
                        name="attempt_reconcile_idx",
                        condition=models.Q(
                            status="redirected", callback_at__isnull=True
                        ),
                    ),
                ),
            ],
        ),
    ]
