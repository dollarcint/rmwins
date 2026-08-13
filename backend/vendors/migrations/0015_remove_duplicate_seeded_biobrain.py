from django.db import migrations


def remove_duplicate_seeded_biobrain(apps, schema_editor):
    ClientIntegration = apps.get_model("vendors", "ClientIntegration")
    Survey = apps.get_model("surveys", "Survey")
    SyncRun = apps.get_model("surveys", "SyncRun")

    seeded = ClientIntegration.objects.filter(
        client__code="biobrain",
        name="Primary BioBrain",
        provider_code="biobrain",
    ).first()
    if seeded is None:
        return
    another_biobrain = ClientIntegration.objects.exclude(pk=seeded.pk).filter(
        provider_code__in=("biobrain", "voqall")
    ).exists()
    has_runtime_data = (
        bool(seeded.encrypted_api_token)
        or Survey.objects.filter(integration_id=seeded.pk).exists()
        or SyncRun.objects.filter(integration_id=seeded.pk).exists()
    )
    if not another_biobrain or has_runtime_data:
        return

    client = seeded.client
    seeded.delete()
    if client.code == "biobrain" and not client.is_active and not client.integrations.exists():
        client.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0014_alter_clientintegration_sync_help_text"),
        ("surveys", "0016_canonical_provider_mappings"),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_seeded_biobrain, migrations.RunPython.noop),
    ]
