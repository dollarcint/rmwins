from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0010_merge_loi_and_vendor_allocation_history"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegrationCredentialState",
            fields=[
                ("provider", models.CharField(max_length=40, primary_key=True, serialize=False)),
                ("credential_fingerprint", models.CharField(max_length=64)),
                ("last_cleared_at", models.DateTimeField(blank=True, null=True)),
                ("last_cleared_links", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "integration credential state"},
        ),
    ]
