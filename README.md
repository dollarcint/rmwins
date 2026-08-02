# Alessar Solutions monorepo

This repository contains the public React website and the authenticated Django research dashboard.

## Structure

- `frontend/` — React + Vite marketing website.
- `backend/` — Django survey inventory and branded authentication.
- `render.yaml` — Render Blueprint for both services and PostgreSQL.

## Local development

Frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Copy `frontend/.env.example` to `frontend/.env.local` when a different dashboard login URL is needed locally.

## Deployment

Create a Render Blueprint from the repository-level `render.yaml`. It provisions the frontend static site, Django web service, and PostgreSQL database. Set `DJANGO_SUPERUSER_PASSWORD`, `INNOVATEMR_ACCESS_TOKEN`, and `VOQALL_ACCESS_KEY` as secret environment variables during Blueprint creation. Connect `api.alessarsolutions.in` as the backend custom domain after the first successful deployment.

The dashboard combines the live InnovateMR and Voqall survey inventories. Voqall market codes are resolved from its `/collection/languages` endpoint so the country filter stays accurate. Supplier credentials must never be committed to Git.
