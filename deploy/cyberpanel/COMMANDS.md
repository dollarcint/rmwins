# CyberPanel one-VPS deployment commands

> This was the original clean-server checklist. The VPS was subsequently deployed with dedicated private ports to preserve its existing stack. Use [`ACTUAL-DEPLOYMENT.md`](ACTUAL-DEPLOYMENT.md) for the real server state and commands.

These commands are configured for:

- VPS IP: `82.29.166.173`.
- Frontend user: `aless4284`, owner of `alessarsolutions.in`.
- Backend user: `apial8464`, owner of `api.alessarsolutions.in`.

Do not paste passwords or the InnovateMR token into chat.

## 0. Publish the current code first

The VPS clones `main` from GitHub, so the required deployment files must be committed and pushed before continuing.

From Windows PowerShell in the local repository:

```powershell
cd "C:\Users\HP\New folder\alessarsolutions"
git status
git diff --stat
```

Review the output before staging because `git add -A` includes all current modifications, new files and deletions:

```powershell
git add -A
git status
git commit -m "Prepare Alessar frontend and backend production deployment"
git push origin main
```

## 1. Connect to the VPS and define both users

```bash
ssh root@82.29.166.173
```

Run on the VPS as `root`:

```bash
export FRONT_USER='aless4284'
export BACK_USER='apial8464'

id "$FRONT_USER"
id "$BACK_USER"
getent passwd "$FRONT_USER"
getent passwd "$BACK_USER"
```

The last two commands show the real home directories. The deployment expects each website user's document root to be `$HOME/public_html`.

## 2. Install shared server packages once

Run as `root`:

```bash
dnf install -y git rsync python3.11 python3.11-pip redis curl ca-certificates
systemctl enable --now redis

python3.11 --version
redis-cli ping
```

`redis-cli ping` must return `PONG`. Redis, MariaDB/MySQL and OpenLiteSpeed are shared services; do not install one copy per website user.

## 3. Deploy the React frontend as its website user

Still as `root`, run:

```bash
sudo -iu "$FRONT_USER" bash -lc '
set -e
cd "$HOME"
if [ ! -d "$HOME/alessarsolutions/.git" ]; then
  git clone https://github.com/kanik-snippet/alessarsolutions.git "$HOME/alessarsolutions"
fi
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
bash deploy/cyberpanel/deploy-frontend.sh
'
```

Check the published files:

```bash
sudo -iu "$FRONT_USER" bash -lc 'ls -la "$HOME/public_html" | head -30'
```

Only the built React files are published in `public_html`; the repository remains outside the public document root.

## 4. Create the backend database in CyberPanel

In CyberPanel:

1. Open **Databases > Create Database**.
2. Select `api.alessarsolutions.in`.
3. Create a database and database user with a strong password.
4. Save the exact generated database name, username and password. CyberPanel may prefix the names.

## 5. Prepare the Django backend as its website user

Run on the VPS as `root`:

```bash
sudo -iu "$BACK_USER" bash -lc '
set -e
cd "$HOME"
if [ ! -d "$HOME/alessarsolutions/.git" ]; then
  git clone https://github.com/kanik-snippet/alessarsolutions.git "$HOME/alessarsolutions"
fi
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
if [ ! -f backend/.env ]; then
  cp deploy/cyberpanel/backend.env.example backend/.env
fi
chmod 600 backend/.env
echo "Django secret suggestion:"
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
echo
echo "Now edit: $HOME/alessarsolutions/backend/.env"
'
```

Open the backend environment file as the backend user:

```bash
sudo -iu "$BACK_USER" bash -lc 'nano "$HOME/alessarsolutions/backend/.env"'
```

Replace every `replace-with-...` value. These production values must remain exactly as shown:

```dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=api.alessarsolutions.in
DJANGO_CSRF_TRUSTED_ORIGINS=https://api.alessarsolutions.in,https://alessarsolutions.in,https://www.alessarsolutions.in
DJANGO_CORS_ALLOWED_ORIGINS=https://alessarsolutions.in,https://www.alessarsolutions.in
DJANGO_BEHIND_HTTPS_PROXY=true
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SECURE_HSTS_SECONDS=0

DB_ENGINE=mysql
DB_HOST=127.0.0.1
DB_PORT=3307

PUBLIC_SUPPLIER_CODE=508
CELERY_BROKER_URL=redis://127.0.0.1:6381/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6381/1
ENABLE_SCHEDULED_JOBS=true
```

Set the real CyberPanel values for `DB_NAME`, `DB_USER`, `DB_PASSWORD`, the generated `DJANGO_SECRET_KEY`, and the real `INNOVATEMR_API_TOKEN`.

## 6. Deploy Django, Gunicorn, Celery Worker and the single Beat

Run as `root`:

```bash
sudo -iu "$BACK_USER" bash -lc '
set -e
cd "$HOME/alessarsolutions"
bash deploy/cyberpanel/deploy-backend.sh
'
```

Check all three processes and the private backend port:

```bash
sudo -iu "$BACK_USER" bash -lc '
cd "$HOME/alessarsolutions"
backend/.venv/bin/supervisorctl -c deploy/cyberpanel/supervisord.conf status
curl -I http://127.0.0.1:8091/login/
'

ss -lntp | grep -E ':(8091|3306|6379)[[:space:]]'
```

Expected Supervisor programs:

- `alessar-web`: `RUNNING`
- `alessar-worker`: `RUNNING`
- `alessar-beat`: `RUNNING`

There must be exactly one `alessar-beat` process.

## 7. Connect the API domain to Gunicorn in OpenLiteSpeed

Open `https://82.29.166.173:7080` and select the virtual host for `api.alessarsolutions.in`.

Under **External App**, create a **Web Server** app:

```text
Name: alessarDjango
Address: 127.0.0.1:8091
Max Connections: 100
Initial Request Timeout: 60
Retry Timeout: 0
Response Buffering: No
```

Create a **Static Context**:

```text
URI: /static/
Location: /home/api.alessarsolutions.in/public_html/static/
Accessible: Yes
Browse: No
```

If `getent passwd` showed a different backend home, use that exact absolute home path instead.

Create a **Proxy Context**:

```text
URI: /
Web Server/Handler: alessarDjango
```

Save and perform an OpenLiteSpeed graceful restart:

```bash
systemctl restart lsws
```

## 8. DNS and SSL

At the DNS provider, point these records to the same VPS IP:

```text
A   @      82.29.166.173
A   www    82.29.166.173
A   api    82.29.166.173
```

In CyberPanel, issue SSL separately for:

- `alessarsolutions.in` (including `www`).
- `api.alessarsolutions.in`.

After both HTTPS URLs work, enable redirect and HSTS:

```bash
sudo -iu "$BACK_USER" bash -lc 'nano "$HOME/alessarsolutions/backend/.env"'
```

Change only:

```dotenv
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_HSTS_SECONDS=31536000
```

Redeploy the backend:

```bash
sudo -iu "$BACK_USER" bash -lc '
cd "$HOME/alessarsolutions"
bash deploy/cyberpanel/deploy-backend.sh
'
```

## 9. Create the first Super Admin and verify production

Only on the new empty database, open:

```text
https://api.alessarsolutions.in/setup/
```

After creating the first Super Admin, `/setup/` intentionally returns 404 and cannot create another one.

Run final checks:

```bash
curl -I https://alessarsolutions.in/
curl -I https://alessarsolutions.in/login
curl -I https://api.alessarsolutions.in/login/
curl -I https://api.alessarsolutions.in/static/accounts/auth.css

sudo -iu "$BACK_USER" bash -lc '
cd "$HOME/alessarsolutions"
backend/.venv/bin/python backend/manage.py check --deploy
backend/.venv/bin/supervisorctl -c deploy/cyberpanel/supervisord.conf status
tail -n 100 "$HOME/app_logs/alessar-worker.log"
tail -n 100 "$HOME/app_logs/alessar-beat.log"
'
```

## 10. Future updates

Frontend update:

```bash
sudo -iu "$FRONT_USER" bash -lc '
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
bash deploy/cyberpanel/deploy-frontend.sh
'
```

Backend update or InnovateMR API-key change:

```bash
sudo -iu "$BACK_USER" bash -lc '
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
bash deploy/cyberpanel/deploy-backend.sh
'
```

The backend deployment restarts Gunicorn, Worker and Beat. When the InnovateMR token fingerprint changes, stale supplier links are removed; when the token is unchanged, the saved links are retained.
