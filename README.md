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
