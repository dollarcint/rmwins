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

Production uses one CyberPanel VPS and one public IP with two isolated website users:

- `alessarsolutions.in`: React static build owned by the frontend website user.
- `api.alessarsolutions.in`: Django, Gunicorn and Celery owned by the backend website user.
- OpenLiteSpeed, MySQL/MariaDB and Redis are shared server services.

Follow [the complete CyberPanel runbook](deploy/cyberpanel/README.md). Supplier credentials and production environment files must never be committed to Git. The repository-level `render.yaml` remains available as an optional Render deployment.
