# SurveyBoard

An authenticated Django dashboard that combines live InnovateMR and BioBrain inventory with client, full-country, CPI, updated-date, and text filters.

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

InnovateMR **Copy link** and CSV links replace `[%%pid%%]` with a cryptographically random 24-character alphanumeric value. BioBrain links use the tracked Alessar start flow below; its two unique IDs are created server-side only when a respondent submits the pre-screener.

The eye action beside each survey link loads that survey's live InnovateMR targeting or BioBrain qualifications on demand. Question responses are cached briefly to keep the dashboard responsive.


## BioBrain tracked respondent flow

Dashboard `Copy link` creates a signed Alessar start URL for BioBrain studies. The public start page loads the live pre-screener, generates a unique 24-character `vq_token` and `vq_uid` when submitted, records the handoff in `SurveySession`, and redirects the respondent to BioBrain.

Configure these browser redirect URLs in the BioBrain supplier account:

- Complete: `https://api.alessarsolutions.in/survey/return/s1/?vq_token=[%%token%%]&vq_uid=[%%vendor_user_id%%]&status_id=[%%status_id%%]`
- Terminate: `https://api.alessarsolutions.in/survey/return/s2/?vq_token=[%%token%%]&vq_uid=[%%vendor_user_id%%]&status_id=[%%status_id%%]`
- Overquota: `https://api.alessarsolutions.in/survey/return/s3/?vq_token=[%%token%%]&vq_uid=[%%vendor_user_id%%]&status_id=[%%status_id%%]`
- Security terminate: `https://api.alessarsolutions.in/survey/return/s4/?vq_token=[%%token%%]&vq_uid=[%%vendor_user_id%%]&status_id=[%%status_id%%]`

Tracked results are visible at `/admin/surveys/surveysession/`. The first terminal return wins, so a later callback cannot overwrite an already recorded result.
