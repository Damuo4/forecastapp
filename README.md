# forecastapp

Industrial distribution / building materials **forecasting and inventory** demo: a React dashboard backed by FastAPI and PostgreSQL, with optional data from **FRED**, **UN Comtrade**, **SEC EDGAR**, and a synthetic **seed** dataset.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

## Repository layout

| Path | Role |
|------|------|
| `frontend/` | React 18 + Vite; dev server proxies `/api` to the backend |
| `backend/` | FastAPI, SQLAlchemy, psycopg 3, `sec_client.py` for SEC requests; Python **3.12** in the Docker image |
| `database/schema.sql` | Postgres DDL (run once against the app database) |
| `ingestion/` | Standalone Python jobs: FRED macro series, Comtrade flows, synthetic inventory seed |
| `docker-compose.yml` | Services: `db` (Postgres 16), `backend`, `frontend` |

## URLs (with Compose running)

- **App:** [http://localhost:5173](http://localhost:5173) (CORS also allows [http://127.0.0.1:5173](http://127.0.0.1:5173))
- **OpenAPI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **DB health:** [http://localhost:8000/api/health/db](http://localhost:8000/api/health/db)

Representative API groups: `/api/dashboard/overview`, `/api/indicators/*`, `/api/recommendations/*`, `/api/data-sources/status`, `/api/data-quality`, `/api/sec/*`, `/api/debug/*`.

## Environment variables

Compose sets **defaults** for Postgres, `DATABASE_URL`, frontend proxy, and file-watcher polling, so you can start without a `.env`.

Copy `.env.example` to `.env` when you need real API keys or overrides:

**Windows (PowerShell)**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux**

```bash
cp .env.example .env
```

| Variable | Used by | Notes |
|----------|---------|--------|
| `POSTGRES_*`, `DATABASE_URL` | Compose, backend, ingestion | If you change DB credentials, keep `DATABASE_URL` aligned (host `db` on the Compose network, port `5432`). |
| `VITE_PROXY_TARGET` | Frontend dev server | Default `http://backend:8000`. |
| `WATCHFILES_FORCE_POLLING`, `CHOKIDAR_USEPOLLING` | Backend / Vite | Default `true` for reliable reloads on Docker Desktop. |
| `FRED_API_KEY` | `ingestion/fred_ingest.py` | [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html); not required to boot the stack. |
| `COMTRADE_*` | `ingestion/comtrade_ingest.py` | Comtrade API key and query defaults (see `.env.example`). |
| `SEC_USER_AGENT`, `SEC_BASE_URL` | Backend (`docker-compose` passes these into the backend container) | SEC expects a **descriptive** `User-Agent` (app name and contact). `SEC_BASE_URL` defaults to `https://data.sec.gov`. |

Optional for local backend only: `SEC_PROOF_OF_LIFE_ENABLED` (default `true` in code) controls certain SEC checks.

## First run

From the repository root:

```bash
docker compose up --build
```

Detached:

```bash
docker compose up --build -d
```

The backend waits until Postgres is healthy.

### Database schema (first time)

Apply `database/schema.sql` once to the `appdb` database (adjust user/db if you changed them).

**Windows (PowerShell), from repo root:**

```powershell
Get-Content database/schema.sql | docker compose exec -T db psql -U postgres -d appdb
```

**macOS / Linux:**

```bash
docker compose exec -T db psql -U postgres -d appdb < database/schema.sql
```

### Optional: load data

With Compose **up** and a populated `.env` (at least `DATABASE_URL` matching Compose, plus API keys where needed), you can run ingestion using the **backend** image so dependencies match (mount `ingestion` and point `DATABASE_URL` at `db` as in `.env.example`):

```bash
docker compose run --rm --env-file .env -v "./ingestion:/work" -w /work backend python seed_inventory_data.py
docker compose run --rm --env-file .env -v "./ingestion:/work" -w /work backend python fred_ingest.py
docker compose run --rm --env-file .env -v "./ingestion:/work" -w /work backend python comtrade_ingest.py
```

`seed_inventory_data.py` only requires `DATABASE_URL`. FRED and Comtrade scripts require their respective API keys and `DATABASE_URL`. **Suggested order:** apply **schema** → run **`comtrade_ingest.py`** first (it upserts `materials` rows the seed expects) → **`fred_ingest.py`** (macro series) → **`seed_inventory_data.py`** (synthetic inventory / orders). If you skip Comtrade, ensure `materials` contains the product `material_code` values from `seed_inventory_data.py` before seeding.

Alternatively, install `backend/requirements.txt` in a local venv, set `DATABASE_URL` to `postgresql+psycopg://postgres:postgres@localhost:5432/appdb`, and run `python ingestion/<script>.py` from the repo root.

## Daily development

- `docker compose up` / `docker compose up -d` — start stack
- `docker compose down` — stop containers
- `docker compose down -v` — stop and **remove** the Postgres volume (full DB reset)
- Hot reload: Vite (frontend), `uvicorn --reload` (backend)
- Logs: `docker compose logs -f` or `docker compose logs -f backend`

## Useful commands

```bash
docker compose build
docker compose ps
docker compose logs -f
```

## Tests

With the stack running:

```bash
docker compose exec backend pytest
docker compose exec frontend npm test
```

You can also create a venv from `backend/requirements.txt` / `npm install` in `frontend/` and run tests locally without Compose.

## Implementation notes

- **`.env` is optional** for booting the stack; defaults in `docker-compose.yml` align with `.env.example`.
- **`frontend_node_modules` volume** — keeps `node_modules` off the bind mount.
- **SEC** — Honor [SEC fair access](https://www.sec.gov/os/webmaster-faq#developers) guidance; set `SEC_USER_AGENT` before relying on SEC-backed routes.

## What this demonstrates

- End-to-end Compose stack (Postgres, API, SPA).
- Dashboard and indicator APIs driven by stored data and configured scenarios.
- External data paths (FRED, Comtrade, SEC) plus reproducible synthetic inventory seeding.
