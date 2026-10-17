# Deploying to Railway

The backend is served at **https://api.iamago.com** — this covers the API, the
OpenAPI docs and the Django admin.

## 1. Create the service

1. New Project → **Deploy from GitHub repo** → this repository.
2. Set the deploy branch (`main` once this work is merged).
3. Add a **PostgreSQL** database to the same project.

`railway.json` is committed, so the build and deploy settings come from the
repo rather than the dashboard: it builds the `prod` stage of the `Dockerfile`,
runs `migrate` as a pre-deploy command, and health-checks `/api/health/`.

## 2. Environment variables

Set these on the **service** (not the database). `${{Postgres.DATABASE_URL}}`
is a Railway reference — type it literally and Railway resolves it.

| Variable | Value | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | References the attached database |
| `DJANGO_SECRET_KEY` | *(generate)* | See below |
| `DJANGO_DEBUG` | `False` | Never `True` in production |
| `DJANGO_ALLOWED_HOSTS` | `api.iamago.com` | Platform hosts are added automatically |
| `CSRF_TRUSTED_ORIGINS` | `https://api.iamago.com` | **Admin login fails without this** |
| `CORS_ALLOWED_ORIGINS` | `https://iamago.com,https://www.iamago.com` | Wherever the frontend is served |
| `TRUSTED_PROXY_COUNT` | `1` | See *Rate limiting* — do not skip |
| `IP_HASH_SALT` | *(generate)* | Rotating it resets everyone's daily counter |
| `SITE_URL` | `https://iamago.com` | The **frontend**, not the API — it builds links inside emails |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | Otherwise nothing is sent |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | *(from your provider)* | |
| `DEFAULT_FROM_EMAIL` | `iamago <hello@iamago.com>` | |
| `GOOGLE_MAPS_API_KEY` | *(server key)* | Geocoding. Restrict by IP |
| `GOOGLE_MAPS_BROWSER_KEY` | *(browser key)* | Served to the frontend. Restrict by HTTP referrer |

Optional: `WEB_CONCURRENCY` (gunicorn workers, default 3),
`ANON_SEARCH_LIMIT_PER_DAY`, `EMAIL_SEARCH_LIMIT_PER_DAY`,
`CONTACT_REQUEST_LIMIT_PER_DAY`.

Generate the two secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 3. Custom domain

1. Service → **Settings → Networking → Custom Domain** → `api.iamago.com`.
2. Railway gives you a CNAME target. Add it at your DNS provider:

   ```
   api   CNAME   <target>.up.railway.app
   ```

   If `iamago.com` is on Cloudflare, set that record to **DNS only** (grey
   cloud) at first — proxying adds a second hop, which changes what
   `TRUSTED_PROXY_COUNT` should be.
3. Railway issues the certificate once DNS resolves.

## 4. First deploy

The pre-deploy command runs migrations, so the schema is created for you.
Then create your admin login and seed the vocabularies:

```bash
railway run python manage.py createsuperuser
railway run python manage.py seed_directory   # modalities and concerns; skip if importing your own
```

Check it:

- `https://api.iamago.com/api/health/` → `{"status":"ok","database":"ok"}`
- `https://api.iamago.com/admin/` → admin login
- `https://api.iamago.com/api/docs/` → Swagger

## 5. Schedule the usage rollup

`DailyStat` rows are what the admin dashboard reads. Add a Railway **cron
service** (same repo and variables, no domain) running nightly:

```
python manage.py rollup_usage --days 2
```

Optionally monthly: `python manage.py prune_usage --days 90`.

## Rate limiting behind a proxy

`TRUSTED_PROXY_COUNT` must match the number of proxies actually in front of the
app, because `X-Forwarded-For` is client-supplied:

- **Too low (0 on Railway)** — every visitor looks like Railway's edge, so they
  all share one daily allowance and the whole site locks after five searches.
- **Too high** — anyone can forge a header and reset their own limit.

On Railway with DNS-only DNS, `1` is right. Verify after deploying: run a few
searches, then open **Usage → Search quotas** in the admin. Several distinct
visitor hashes means it is working; a single row that everyone shares means the
value is too low.

## Why the health check needs no redirect

`SECURE_SSL_REDIRECT` is on in production, and Railway's health check reaches
the container directly without `X-Forwarded-Proto`. Django would answer it with
a 301, which the platform counts as a failure — so the deploy would never go
live while the app was perfectly healthy. `SECURE_REDIRECT_EXEMPT` carves out
`/api/health/` only. The path must keep its trailing slash: `/api/health` would
redirect and fail for the same reason.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `DisallowedHost` | `DJANGO_ALLOWED_HOSTS` missing `api.iamago.com` |
| Health check times out, app looks fine | Not binding `$PORT`, or the path lost its trailing slash |
| Admin login rejects a correct password | `CSRF_TRUSTED_ORIGINS` missing `https://api.iamago.com` |
| Frontend requests blocked in the browser | `CORS_ALLOWED_ORIGINS` missing the frontend origin |
| Everyone rate-limited at once | `TRUSTED_PROXY_COUNT` too low |
| Emails never arrive | `EMAIL_BACKEND` still the console default |
| Admin CSS missing | `collectstatic` failed during build — check the build log |

If the health check fails on an otherwise healthy container, the next thing to
try is binding IPv6 as well: add a second `--bind "[::]:${PORT}"` to the
`CMD` in the `Dockerfile`.

## The frontend

Separate deploy — see `DEPLOY.md` in the frontend repo. Point it at this API
with `VITE_API_BASE_URL=https://api.iamago.com/api` at **build** time (Vite
inlines `VITE_*` into the bundle), and make sure its origin is in
`CORS_ALLOWED_ORIGINS` above.

Preview deployments get a new hostname on every build, so they cannot be listed
individually. Allow them with a pattern instead:

```
CORS_ALLOWED_ORIGIN_REGEXES=^https://iamago-app-frontend-[a-z0-9-]+\.vercel\.app$
```

Keep it anchored at both ends. An unanchored pattern would also match
`https://iamago-app-frontend-evil.attacker.com`, which is the usual way this
kind of rule goes wrong — `tests/test_cors.py` holds that line.
