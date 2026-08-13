from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vendors", "0013_cint_country_language_inventory")]

    operations = [
        migrations.AlterField(
            model_name="clientintegration",
            name="detail_refresh_batch",
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text="Survey detail records refreshed after each inventory sync.",
                validators=[MinValueValidator(0), MaxValueValidator(25)],
            ),
        ),
        migrations.AlterField(
            model_name="clientintegration",
            name="sync_interval_seconds",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Minimum interval between inventory syncs for this integration.",
                validators=[MinValueValidator(60)],
            ),
        ),
    ]
