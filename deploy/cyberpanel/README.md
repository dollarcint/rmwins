# Enligne Surveys on one CyberPanel VPS

The current VPS state and exact maintenance commands are in [`ACTUAL-DEPLOYMENT.md`](ACTUAL-DEPLOYMENT.md).

The original clean-server checklist is in [`COMMANDS.md`](COMMANDS.md).

This deployment uses one public IP and two CyberPanel websites with separate Linux users.

| Website | Owner | Purpose |
| --- | --- | --- |
| `alessarsolutions.in` | frontend website user | React static build in `$HOME/public_html` |
| `api.alessarsolutions.in` | backend website user | Django app, Gunicorn and Celery outside `public_html` |

OpenLiteSpeed, MySQL/MariaDB and Redis are shared server services. Gunicorn is private on `127.0.0.1:8091`; database, Redis and Gunicorn ports must not be exposed publicly.

## 1. DNS and CyberPanel

Point all records to the same VPS IP:

| Type | Host | Target |
| --- | --- | --- |
| A | `@` | CyberPanel VPS IPv4 |
| A | `www` | CyberPanel VPS IPv4 |
| A | `api` | CyberPanel VPS IPv4 |

The two websites should remain separate CyberPanel websites, not an addon domain. Issue SSL for both websites from CyberPanel after DNS resolves.

For the backend website, create a MySQL database and user in CyberPanel. Put those exact generated names in `backend/.env`; CyberPanel may prefix database/user names.

Redis must run once at server level:

```bash
redis-cli ping
```

Expected output is `PONG`. If Redis is missing, install/enable it from CyberPanel or as the VPS root user. Do not run a separate Redis instance per website.

## 2. Required server runtimes

The frontend user needs Node.js 22 and npm. The backend user needs Python 3, venv support, Git and `rsync`. Install these once as root if they are not already available:

```bash
sudo dnf install -y git rsync python3.11 python3.11-pip redis curl ca-certificates
sudo systemctl enable --now redis
```

Verify that ports `3306`, `6379` and `8091` are not open in the VPS firewall.

## 3. Frontend website user

SSH as the frontend website user. Do not clone the repository inside `public_html`:

```bash
cd "$HOME"
git clone https://github.com/kanik-snippet/alessarsolutions.git alessarsolutions
cd "$HOME/alessarsolutions"
bash deploy/cyberpanel/deploy-frontend.sh
```

The script builds React with `VITE_DASHBOARD_URL=https://api.alessarsolutions.in` and publishes only `frontend/dist` to the frontend user's `public_html`. The included `.htaccess` sends SPA routes such as `/login` to `index.html`.

If the CyberPanel website uses a nonstandard document root:

```bash
PUBLIC_DIR=/absolute/frontend/document/root bash deploy/cyberpanel/deploy-frontend.sh
```

The script intentionally refuses deployment outside the current user's `public_html` tree.

## 4. Backend website user

SSH as the backend website user and clone the repository outside `public_html`:

```bash
cd "$HOME"
git clone https://github.com/kanik-snippet/alessarsolutions.git alessarsolutions
cd "$HOME/alessarsolutions"
cp deploy/cyberpanel/backend.env.example backend/.env
chmod 600 backend/.env
nano backend/.env
```

Set the real Django secret, CyberPanel MySQL credentials and InnovateMR token. Keep:

```dotenv
PUBLIC_SUPPLIER_CODE=508
CELERY_BROKER_URL=redis://127.0.0.1:6381/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6381/1
```

Before SSL is active, keep `DJANGO_SECURE_SSL_REDIRECT=false` and HSTS at zero. Deploy:

```bash
cd "$HOME/alessarsolutions"
bash deploy/cyberpanel/deploy-backend.sh
```

The rootless installer creates `backend/.venv`, applies migrations, collects static files, copies static assets to the backend user's `public_html/static`, and starts these processes under the backend user:

- `alessar-web`: Gunicorn on `127.0.0.1:8091`.
- `alessar-worker`: Celery worker.
- `alessar-beat`: the only Celery Beat instance.

It also installs an `@reboot` cron entry that restarts Supervisor after a VPS reboot. Cron does not run API sync jobs; Beat schedules them and the worker executes them through Redis.

Check processes:

```bash
backend/.venv/bin/supervisorctl -c deploy/cyberpanel/supervisord.conf status
curl -I http://127.0.0.1:8091/login/
tail -f "$HOME/app_logs/alessar-worker.log"
```

## 5. OpenLiteSpeed reverse proxy for the API website

Use OpenLiteSpeed WebAdmin (`https://VPS-IP:7080`) or the equivalent CyberPanel vHost controls for the `api.alessarsolutions.in` virtual host.

Create a virtual-host-level **Web Server External App**:

- Name: `alessarDjango`
- Address: `127.0.0.1:8091`
- Max Connections: `100`
- Initial Request Timeout: `60`
- Retry Timeout: `0`
- Response Buffering: `No`

Create a **Proxy Context**:

- URI: `/`
- Web Server/Handler: `alessarDjango`

Create a more-specific **Static Context** before the proxy context:

- URI: `/static/`
- Location: the backend website user's absolute `$HOME/public_html/static/` path
- Accessible: `Yes`
- Browse: `No`

Apply a graceful OpenLiteSpeed restart. OpenLiteSpeed officially supports proxying an entire virtual host to a private HTTP application through an External App plus Proxy Context.

After CyberPanel SSL works for both domains, change the backend `.env` values:

```dotenv
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_HSTS_SECONDS=31536000
```

Then rerun `bash deploy/cyberpanel/deploy-backend.sh`.

## 6. First administrator and checks

On a new database, open `https://api.alessarsolutions.in/setup/` once to create the first Super Admin. Thereafter use `https://alessarsolutions.in/login`.

Verify:

```bash
curl -I https://alessarsolutions.in/
curl -I https://alessarsolutions.in/login
curl -I https://api.alessarsolutions.in/login/
curl -I https://api.alessarsolutions.in/static/accounts/auth.css
```

In CyberPanel, configure automatic database backups and copy backups off the VPS. A same-server backup alone does not protect against VPS loss.

## 7. Updates

Frontend user:

```bash
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
bash deploy/cyberpanel/deploy-frontend.sh
```

Backend user:

```bash
cd "$HOME/alessarsolutions"
git pull --ff-only origin main
bash deploy/cyberpanel/deploy-backend.sh
```

When the InnovateMR token changes, the backend deploy restarts Worker and Beat. The fingerprint guard clears stale InnovateMR links for a changed token and retains current links when the token is unchanged.
