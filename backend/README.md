# SurveyBoard

An authenticated Django dashboard that combines the live InnovateMR and Voqall survey inventories with company, country, name, and text filters.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

Open http://127.0.0.1:8000/. The browser refreshes the inventory every 30 seconds; the Django backend keeps a short 12-second cache to avoid duplicate upstream requests.

## Configuration

Set these supplier secrets in the environment:

- `INNOVATEMR_ACCESS_TOKEN`: InnovateMR supplier access token.
- `VOQALL_ACCESS_KEY`: Voqall partner access key.

Optional settings:

- `INNOVATEMR_SURVEY_URL`, `VOQALL_SURVEY_URL`, `VOQALL_LANGUAGES_URL`: override supplier endpoints.
- `SURVEY_FEED_TIMEOUT`: upstream timeout in seconds (default `15`).
- `SURVEY_CACHE_SECONDS`: backend cache duration (default `12`).
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`: standard deployment settings.

Every **Copy link**, **Open**, and CSV export action populates the supplier-specific respondent field (`PID`, `vq_uid`, or `user_id`) with the fixed user ID `omega`.
