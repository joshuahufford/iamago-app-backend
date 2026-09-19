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
