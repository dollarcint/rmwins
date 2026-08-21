from django.db import migrations


COUNTRY_CODES = {
    "Argentina": "AR", "Australia": "AU", "Austria": "AT", "Belgium": "BE",
    "Brazil": "BR", "Canada": "CA", "Chile": "CL", "China": "CN",
    "Colombia": "CO", "Croatia": "HR", "Denmark": "DK", "Egypt": "EG",
    "Finland": "FI", "France": "FR", "Germany": "DE", "Hong Kong": "HK",
    "India": "IN", "Indonesia": "ID", "Ireland": "IE", "Israel": "IL",
    "Italy": "IT", "Japan": "JP", "Kenya": "KE", "Luxembourg": "LU",
    "Malaysia": "MY", "Mexico": "MX", "Netherlands": "NL", "New Zealand": "NZ",
    "Norway": "NO", "Philippines": "PH", "Poland": "PL", "Republic of Korea": "KR",
    "Romania": "RO", "Saudi Arabia": "SA", "Singapore": "SG", "South Africa": "ZA",
    "Spain": "ES", "Sweden": "SE", "Switzerland": "CH", "Taiwan": "TW",
    "Thailand": "TH", "Turkey": "TR", "United Arab Emirates": "AE",
    "United Kingdom": "GB", "United States": "US",
}


def backfill_country_codes(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    for country, code in COUNTRY_CODES.items():
        Survey.objects.filter(country_code="", country__iexact=country).update(country_code=code)


class Migration(migrations.Migration):
    dependencies = [("surveys", "0028_survey_created_by_survey_inventory_source_and_more")]
    operations = [migrations.RunPython(backfill_country_codes, migrations.RunPython.noop)]
