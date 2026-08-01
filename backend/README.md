# SurveyBoard

A no-login Django dashboard that reads the Enligne survey feed live, extracts the company from each entry URL, and provides company, country, name, and text filters.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

Open http://127.0.0.1:8000/. The browser refreshes the feed every 30 seconds; the Django backend keeps a short 12-second cache to avoid duplicate upstream requests.

## Configuration

These optional environment variables are supported:

- `SURVEY_FEED_URL`: replaces the default feed URL.
- `SURVEY_FEED_TIMEOUT`: upstream timeout in seconds (default `15`).
- `SURVEY_CACHE_SECONDS`: backend cache duration (default `12`).
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`: standard deployment settings.

Every **Copy link**, **Open**, and CSV export action replaces the feed's `{userId}` value with the fixed user ID `opop` for every company and survey.
