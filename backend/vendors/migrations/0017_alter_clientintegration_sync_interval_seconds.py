from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0016_align_client_provider_codes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientintegration",
            name="sync_interval_seconds",
            field=models.PositiveIntegerField(
                default=60,
                help_text=(
                    "Minimum interval between inventory syncs "
                    "(30 seconds; some providers require 60)."
                ),
                validators=[MinValueValidator(30)],
            ),
        ),
    ]
