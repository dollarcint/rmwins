from django.db import migrations


def align_client_provider_codes(apps, schema_editor):
    Client = apps.get_model("vendors", "Client")
    for client in Client.objects.prefetch_related("integrations"):
        providers = {
            str(provider).strip().lower()
            for provider in client.integrations.values_list("provider_code", flat=True)
            if str(provider).strip()
        }
        if len(providers) == 1:
            provider = providers.pop()
            if client.provider_code != provider:
                client.provider_code = provider
                client.save(update_fields=["provider_code"])


class Migration(migrations.Migration):
    dependencies = [("vendors", "0015_remove_duplicate_seeded_biobrain")]

    operations = [
        migrations.RunPython(align_client_provider_codes, migrations.RunPython.noop),
    ]
