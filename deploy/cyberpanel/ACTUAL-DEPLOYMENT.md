# Alessar VPS deployment: actual state

VPS: `82.29.166.173` (AlmaLinux 9)

## Isolated services now running

| Component | Linux user | Address | Manager |
| --- | --- | --- | --- |
| React frontend | `aless4284` | `127.0.0.1:8092` | `alessar-frontend.service` |
| Django/Gunicorn | `apial8464` | `127.0.0.1:8091` | rootless Supervisor |
| Celery Redis | `apial8464` | `127.0.0.1:6381` | rootless Supervisor |
| Celery Worker | `apial8464` | private | rootless Supervisor |
| Celery Beat | `apial8464` | private; exactly one | rootless Supervisor |
| Alessar MariaDB | `apial8464` | `127.0.0.1:3307` | `alessar-mysql.service` |

The existing Nginx, OpenLiteSpeed, MariaDB `3306` and Redis `6379` configurations were not replaced. Alessar has a separate database named `alessar_prod` and database user `alessar_app` on its isolated MariaDB instance.

## Status commands

Run from Windows PowerShell:

```powershell
ssh root@82.29.166.173 "systemctl status alessar-frontend.service alessar-mysql.service --no-pager"
ssh root@82.29.166.173 "runuser -u apial8464 -- env HOME=/home/api.alessarsolutions.in /home/api.alessarsolutions.in/alessarsolutions/backend/.venv/bin/supervisorctl -c /home/api.alessarsolutions.in/alessarsolutions/deploy/cyberpanel/supervisord.conf status"
ssh root@82.29.166.173 "ss -lntp | grep -E ':(3307|6381|8091|8092)[[:space:]]'"
```

Expected programs:

```text
alessar-beat     RUNNING
alessar-redis    RUNNING
alessar-web      RUNNING
alessar-worker   RUNNING
```

Internal endpoint checks:

```powershell
ssh root@82.29.166.173 "curl -I http://127.0.0.1:8092/login"
ssh root@82.29.166.173 "curl -I -H 'Host: api.alessarsolutions.in' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8091/setup/"
ssh root@82.29.166.173 "redis-cli -p 6381 ping"
```

Non-secret database and supplier verification:

```powershell
ssh root@82.29.166.173 "runuser -u apial8464 -- env HOME=/home/api.alessarsolutions.in bash -c 'cd /home/api.alessarsolutions.in/alessarsolutions/backend && .venv/bin/python ../deploy/cyberpanel/verify-backend.py'"
```

## Logs

```powershell
ssh root@82.29.166.173 "tail -f /home/api.alessarsolutions.in/app_logs/alessar-worker.log"
ssh root@82.29.166.173 "tail -f /home/api.alessarsolutions.in/app_logs/alessar-beat.log"
ssh root@82.29.166.173 "tail -f /home/api.alessarsolutions.in/app_logs/alessar-web-error.log"
ssh root@82.29.166.173 "tail -f /home/api.alessarsolutions.in/app_logs/alessar-mysql.log"
```

## Safe service restarts

Frontend only:

```powershell
ssh root@82.29.166.173 "systemctl restart alessar-frontend.service"
```

Backend, Redis, Worker and Beat only:

```powershell
ssh root@82.29.166.173 "runuser -u apial8464 -- env HOME=/home/api.alessarsolutions.in /home/api.alessarsolutions.in/alessarsolutions/backend/.venv/bin/supervisorctl -c /home/api.alessarsolutions.in/alessarsolutions/deploy/cyberpanel/supervisord.conf restart all"
```

Alessar MySQL only:

```powershell
ssh root@82.29.166.173 "systemctl restart alessar-mysql.service"
```

## API-key update

Edit only the protected backend environment:

```powershell
ssh root@82.29.166.173
runuser -u apial8464 -- nano /home/api.alessarsolutions.in/alessarsolutions/backend/.env
```

Change `INNOVATEMR_API_TOKEN`, then restart the backend group:

```bash
runuser -u apial8464 -- env HOME=/home/api.alessarsolutions.in /home/api.alessarsolutions.in/alessarsolutions/backend/.venv/bin/supervisorctl -c /home/api.alessarsolutions.in/alessarsolutions/deploy/cyberpanel/supervisord.conf restart all
```

The fingerprint guard removes stale supplier links when the token changes and retains them when the token remains unchanged.

## Public routing is intentionally pending

DNS currently points to the previous Render/Cloudflare deployment. The isolated VPS services are not exposed publicly. Making the two domains live requires:

1. Add only the two new hostname server blocks from `nginx-alessar-http.conf`.
2. Validate Nginx configuration and perform one graceful reload.
3. Change the three DNS A records to `82.29.166.173`.
4. Issue trusted SSL certificates for the two new domains.
5. Enable HTTPS redirect and Django HSTS after HTTPS validation.

No existing Nginx vhost file needs to be edited.
