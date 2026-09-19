# iamago-app-backend

Django + Django REST Framework API for the iamago web app, backed by PostgreSQL
and using JWT authentication.

The companion frontend lives in [`iamago-app-frontend`](https://github.com/joshuahufford/iamago-app-frontend).

## Stack

| Concern         | Choice                                   |
| --------------- | ---------------------------------------- |
| Framework       | Django 5.2                               |
| API             | Django REST Framework 3.16               |
| Auth            | `djangorestframework-simplejwt` (JWT)    |
| Database        | PostgreSQL 16                            |
| API docs        | `drf-spectacular` (OpenAPI 3 / Swagger)  |
| Tests           | pytest + pytest-django                   |
| Lint / format   | ruff                                     |

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

The API is then on http://localhost:8000 with Swagger UI at
http://localhost:8000/api/docs/.

## Quick start (local Python)

Requires a PostgreSQL 16 server reachable at the `DATABASE_URL` in your `.env`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Project layout

```
config/            Django project: settings, root urls, wsgi/asgi entry points
apps/
  accounts/        Custom email-based User, Profile, auth endpoints
  common/          Shared base model, pagination, error envelope, health check
  directory/       Practitioners, modalities, concerns, and the matching engine
  analytics/       Usage tracking, daily rollups, and the search rate limit
tests/             pytest suite (API-level, hits the real database)
```

### Conventions

- **Users are identified by email.** `accounts.User` replaces Django's default
  user model; there is no username field. A `Profile` row is created
  automatically for every user via a `post_save` signal.
- **Domain models inherit `apps.common.models.TimeStampedModel`**, which supplies
  a UUID primary key plus `created_at` / `updated_at`.
- **Errors use one envelope.** `apps.common.exceptions.exception_handler` turns
  every DRF error into `{"detail": str, "errors": {field: [msg]}}` so the
  frontend has a single shape to handle.
- **Endpoints require authentication by default** (`IsAuthenticated` is the
  global default); opt out explicitly with `permission_classes = [AllowAny]`.

## API

| Method      | Path                        | Purpose                              |
| ----------- | --------------------------- | ------------------------------------ |
| `GET`       | `/api/health/`              | Liveness probe incl. database check   |
| `POST`      | `/api/auth/register/`       | Create an account                     |
| `POST`      | `/api/auth/login/`          | Obtain access + refresh tokens        |
| `POST`      | `/api/auth/refresh/`        | Exchange a refresh token              |
| `POST`      | `/api/auth/verify/`         | Validate a token                      |
| `GET/PATCH` | `/api/auth/me/`             | Read / update the current user        |
| `POST`      | `/api/auth/change-password/`| Change the current user's password    |
| `GET`       | `/api/directory/concerns/`  | Health concerns for the quiz (public) |
| `GET`       | `/api/directory/modalities/`| Care types for the quiz (public)      |
| `POST`      | `/api/directory/recommendations/` | Run the quiz, get max 3 matches |
| `GET`       | `/api/directory/recommendations/<id>/?token=` | Re-open a past run  |
| `GET`       | `/api/directory/practitioners/<id>/` | One published listing        |
| `GET`       | `/api/directory/geocode/?q=` | Resolve a place to coordinates       |
| `POST`      | `/api/directory/events/`    | Record a practitioner click-through   |
| `GET`       | `/api/directory/map-config/` | Browser Maps key, if configured      |
| `GET`       | `/api/schema/`              | OpenAPI 3 schema                      |
| `GET`       | `/api/docs/`                | Swagger UI                            |
| `GET`       | `/api/redoc/`               | ReDoc                                 |
| `GET`       | `/admin/`                   | Django admin                          |

Access tokens last 15 minutes and refresh tokens 7 days; refresh tokens rotate
on use. Both lifetimes are configurable via environment variables.

## Configuration

Every setting is read from the environment — see `.env.example` for the full
list. `DJANGO_SECRET_KEY` and `DATABASE_URL` are the two you must set for a real
deployment. With `DJANGO_DEBUG=False` the app enables HSTS, SSL redirect and
secure cookies automatically.

## Development

```bash
pytest                       # run the test suite
pytest --cov                 # with coverage
ruff check . && ruff format . # lint and format
python manage.py makemigrations
```

## Adding a feature app

```bash
mkdir -p apps/<name>/migrations && touch apps/<name>/__init__.py apps/<name>/migrations/__init__.py
```

Add `"apps.<name>"` to `INSTALLED_APPS`, inherit models from `TimeStampedModel`,
and include the app's `urls.py` from `config/urls.py` under `/api/`.

## The directory and the recommendation engine

The public discovery flow is the heart of the product: a visitor answers a
short quiz and gets **at most three** practitioners back, each with the reasons
it was chosen. Nothing in that flow requires an account.

### Data model

- **`Modality`** — an approach (Acupuncture, Functional Medicine, …). What a
  patient picks when they already know the kind of care they want.
- **`HealthConcern`** — what the patient is actually trying to solve. Most
  people know their problem, not the modality, so this is the primary input.
  Each concern records the modalities that typically address it, which lets the
  engine rank sensibly when no modality preference is given.
- **`Practitioner`** — the listing, including coordinates, availability and tier.
- **`RecommendationRequest` / `Recommendation`** — one quiz run and its results,
  persisted so a patient can revisit them.

### Tiers

| Tier       | Meaning                                    | Effect                  |
| ---------- | ------------------------------------------ | ----------------------- |
| `partner`  | Paying partner                              | Badge + strongest boost |
| `verified` | Vetted by us internally, not paying         | Badge + small boost     |
| `standard` | Everyone else                               | No badge, no boost      |

Set the tier in the Django admin. Boosts are additive and deliberately smaller
than the concern weight, so **a paying partner can never outrank a materially
better clinical match** — `tests/test_matching.py` enforces exactly that.

### Scoring

| Component            | Max | Basis                                        |
| -------------------- | --- | -------------------------------------------- |
| Concern overlap      | 40  | Share of the patient's concerns treated       |
| Modality overlap     | 30  | Share of requested modalities offered         |
| Proximity            | 20  | Linear decay from the patient to the radius   |
| Accepting patients   |  5  | Flat                                          |
| Telehealth           |  5  | Flat, when the patient is open to it          |
| Tier boost           | +12 / +6 / 0 | partner / verified / standard        |

Practitioners outside the radius are dropped unless they offer telehealth and
the patient accepted it. Ties break toward the nearer practitioner, then by
name, so repeated runs of the same quiz return the same list.

Geography uses a bounding-box pre-filter in SQL followed by an exact haversine
pass in Python. That keeps PostGIS out of the stack; revisit it if the listing
count or query volume grows significantly.

### Google Maps

Two keys, both optional:

- `GOOGLE_MAPS_API_KEY` — server-side, used for geocoding. Restrict by IP.
- `GOOGLE_MAPS_BROWSER_KEY` — served to the frontend by `/api/directory/map-config/`
  so it can be rotated in one place. It ships in the browser either way, so
  restrict it by HTTP referrer.

With neither set, geocoding falls back to a small bundled table of US cities and
the frontend renders results as a list. This keeps the whole flow runnable in
development and CI without credentials — it is not a production geocoder.

### Seeding demo data

```bash
python manage.py seed_directory          # idempotent
python manage.py seed_directory --flush  # replace existing practitioners
```

Seeds 12 modalities, 12 concerns and 14 practitioners across Austin, Denver,
New York and Seattle, with a mix of all three tiers.

## Distances are in miles

Everything stored and returned is miles — `radius_miles` on a request,
`distance_miles` on a recommendation, and `haversine_miles` in the engine. The
`0002_distances_in_miles` migration renames the old kilometre columns and
converts the values in place, so existing rows survive; it reverses cleanly too.

## Running the admin

The admin is the product for whoever curates the directory, so it is built for
data entry rather than as a bare model browser.

```bash
python manage.py createsuperuser
python manage.py seed_directory     # demo data, idempotent
python manage.py runserver
```

### Practitioners

The changelist is the main working screen:

- **Ready?** tells you what is stopping a listing from ever being recommended —
  missing coordinates, no concerns, no approaches. A listing with no concerns
  is effectively invisible, so this is the column to scan.
- **Referrals** shows impressions and click-throughs per listing. This is what
  a partner is paying for.
- **Published** and **Accepting new patients** are editable inline, so you can
  triage a whole page and hit Save once.

Actions on selected rows: publish, unpublish, **look up coordinates from the
address** (so you never have to find a latitude by hand), set tier, and export
to CSV.

### Bulk import

**Import from CSV** on the practitioner list takes a spreadsheet export. Only
`display_name` is required. `modalities` and `concerns` accept several values
separated by a pipe (`Acupuncture|Herbal Medicine`), and any name that does not
exist yet is created for you.

Rows are matched on `display_name`, so re-uploading a corrected file updates the
existing listings instead of duplicating them. Imports land as drafts unless you
tick *Publish*, and rows with no coordinates are geocoded on the way in.

### Usage

Under **Usage**:

- **Daily usage** — the dashboard. Searches, unique visitors, *Found nobody*
  (your coverage gaps, highlighted when they pass 20%), recommendations served,
  impressions, clicks, click rate, emails captured and blocked requests.
- **Practitioner events** — the raw impression and click log.
- **Search quotas** — per-visitor daily counters, for spotting abuse.

All three are read-only. Editing a rollup would only be lying to yourself.

```bash
python manage.py rollup_usage            # last 7 days
python manage.py rollup_usage --all      # every day with activity
python manage.py prune_usage --days 90   # drop raw rows past retention
```

`rollup_usage` is idempotent — re-running a day recomputes it rather than
double-counting. Schedule it nightly.

## Usage tracking

| What                       | Where it lives                                  |
| -------------------------- | ----------------------------------------------- |
| The search and its answers | `RecommendationRequest` (concerns, modalities, location, `result_count`) |
| Zero-result searches       | `RecommendationRequest.result_count = 0`         |
| Impressions                | `PractitionerEvent`, written **server-side**     |
| Clicks                     | `PractitionerEvent`, reported by the browser     |
| Daily rollups              | `DailyStat`                                      |

Impressions are written by the server when a recommendation is produced, not
reported by the client, so a partner's numbers cannot be inflated by anyone
calling the API. The public event endpoint refuses `impression` for that reason,
and refuses unpublished practitioners.

`tier_at_event` is denormalised onto each event, so historical partner reporting
stays honest after a tier changes.

## Rate limiting

The directory is the asset, so searching it is metered per visitor per day:

| Setting                      | Default | Meaning                              |
| ---------------------------- | ------- | ------------------------------------ |
| `ANON_SEARCH_LIMIT_PER_DAY`  | 5       | Free searches, no email, invisible    |
| `EMAIL_SEARCH_LIMIT_PER_DAY` | 25      | Ceiling once an email is supplied     |
| `TRUSTED_PROXY_COUNT`        | 0       | Proxies in front of the app           |
| `IP_HASH_SALT`               | —       | Falls back to `SECRET_KEY`            |

Past the anonymous allowance the API answers `429` with
`code: "email_required"`; the frontend then shows an email field and retries.
Past the email allowance it answers `429` with `code: "rate_limited"`. An email
raises the ceiling rather than removing it — it is a speed bump for a scraper,
not a licence to take the whole directory.

**Visitor addresses are never stored.** They are salted and hashed on the way
in, which is enough to count searches without holding an identifier we would
then have to protect. Rotating `IP_HASH_SALT` resets everyone's counter.

> **`TRUSTED_PROXY_COUNT` matters.** `X-Forwarded-For` is client-supplied. If
> you deploy behind a proxy and leave this at 0, every visitor looks like the
> proxy and shares one allowance. If you set it without actually having that
> many proxies, anyone can forge a header and reset their own limit. Set it to
> the number of proxies that really sit in front of the app.
