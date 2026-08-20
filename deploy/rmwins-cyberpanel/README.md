# RMWins private deployment on the CyberPanel VPS

This directory is intentionally separate from `deploy/cyberpanel`. It deploys
RMWins under the existing CyberPanel account without modifying or stopping the
Alessar stack.

## Private service layout

| Component | Address | Data policy | Manager |
| --- | --- | --- | --- |
| PostgreSQL 16 | `127.0.0.1:5432` | Server service; dedicated `rmwins_prod` and `rmwins_vault` roles/databases | `postgresql.service` |
| Celery Redis | `127.0.0.1:6382` | AOF + RDB; broker DB 0, results DB 1 | RMWins Supervisor |
| Cache Redis | `127.0.0.1:6383` | No persistence; cache DBs 0 and 1 | RMWins Supervisor |
| Django/Gunicorn | `127.0.0.1:8093` | Three workers, two threads each | RMWins Supervisor |
| React static server | `127.0.0.1:8094` | Build in `$HOME/app/frontend-dist` | `rmwins-frontend.service` |

All application processes run as `wwwrm1759`, whose verified home is
`/home/www.rmwinsights.com`. Ports 5432, 6382, 6383, 8093, and 8094 must remain
closed in firewalld. PostgreSQL and every application service bind only to
loopback.

The initial environment sets `ENABLE_SCHEDULED_JOBS=false`. Do not enable it
while the old Alessar scheduler is live or before provider credentials are
explicitly authorized for RMWins.

## Snapshot deployment

Build the frontend from the repository root with Node 22 so the final output is
the root `dist/` directory:

```bash
VITE_DASHBOARD_URL=https://api.rmwinsights.com npm run build
```

Create a trusted snapshot containing the current working tree and `dist/`, but
not Git metadata, environments, virtualenvs, dependencies, or caches. Upload it
to a unique file under `/var/tmp`. Before execution, pin both inputs behind a
root-owned boundary.

Run as root:

```bash
install -d -m 0750 -o root -g root /var/lib/rmwins-deploy
install -m 0700 -o root -g root \
  /var/tmp/rmwins-deploy-private.sh \
  /var/lib/rmwins-deploy/deploy-private-snapshot.sh
chown root:root /var/tmp/rmwins-snapshot.tar.gz
chmod 0600 /var/tmp/rmwins-snapshot.tar.gz
bash -n /var/lib/rmwins-deploy/deploy-private-snapshot.sh
SNAPSHOT_ARCHIVE=/var/tmp/rmwins-snapshot.tar.gz \
  /var/lib/rmwins-deploy/deploy-private-snapshot.sh
```

The wrapper hashes and copies the uploaded archive into its protected state
directory before listing or extracting it. It refuses symlinked, non-root-owned,
or group/world-accessible inputs.

The wrapper:

- verifies the exact user/home/target paths and loopback/firewall isolation;
- backs up the prior app, frontend, environment, and both PostgreSQL databases;
- generates first-deploy secrets and two password-protected Redis configs as
  root-owned, group-readable service files (`root:wwwrm1759`, mode `0640`),
  without printing secrets;
- preserves those protected files on later deployments;
- provisions separate least-privilege PostgreSQL roles/databases;
- migrates both Django databases and runs `collectstatic` plus `check --deploy`;
- creates `rmwins_admin` privately and stores its generated password only in
  `/home/www.rmwinsights.com/.config/rmwins/admin-credentials`
  (`root:root`, mode `0600`);
- manages the bootstrap administrator and every future staff/superuser account
  through Django Admin at `https://api.rmwinsights.com/admin/`;
- never resets, recreates, or duplicates an established Django administrator
  during later deployments;
- installs/starts only the two `rmwins-*` systemd units;
- verifies PostgreSQL, both Redis instances, Gunicorn, the frontend, and every
  Supervisor process before reporting success.

It does **not** edit/reload public Nginx, request certificates, change DNS,
modify the firewall, or restart Alessar.

## Private verification

Run as root:

```bash
systemctl status postgresql.service rmwins-supervisor.service rmwins-frontend.service --no-pager
runuser -u wwwrm1759 -- env HOME=/home/www.rmwinsights.com \
  /home/www.rmwinsights.com/rmwins/backend/.venv/bin/supervisorctl \
  -c /home/www.rmwinsights.com/rmwins/deploy/rmwins-cyberpanel/supervisord.conf status
curl --fail http://127.0.0.1:8094/__health
curl --fail -H 'Host: api.rmwinsights.com' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8093/api/v1/auth/session/
ss -lntp | grep -E ':(5432|6382|6383|8093|8094)[[:space:]]'
firewall-cmd --list-ports
```

Never display `backend.env`, either Redis config, or `admin-credentials` in
terminal output or logs. Read the generated administrator file only as root.
Provider secrets remain a cutover blocker until the owner authorizes fresh values.

Production login is rendered only by the React frontend at
`https://www.rmwinsights.com/login`. The API host redirects `/login/` there.
The historical `/setup` URL redirects to Django Admin. Use the protected
bootstrap credentials for the first admin login, immediately change that
password in Django Admin, and create/manage every future admin there.

## Public cutover (only after private health passes)

`nginx-rmwins-http.conf` is the pre-certificate public template.
`nginx-rmwins-https.conf` is the production TLS template and expects one SAN
certificate under `/etc/letsencrypt/live/rmwinsights.com/` covering:

- `rmwinsights.com`
- `www.rmwinsights.com`
- `api.rmwinsights.com`

Before installing either template, confirm no existing Nginx server block owns
those hostnames and validate the full Nginx configuration with `nginx -t`.
Use DNS-only records unless trusted Cloudflare proxy ranges and real-IP handling
are configured. Only after external HTTPS validation should Django SSL redirect,
HSTS, and scheduled provider jobs be considered for enablement.
