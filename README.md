# forecastapp

Hello world monorepo using React, FastAPI, and PostgreSQL with Docker Compose.

## Stack

- `frontend/`: React + Vite
- `backend/`: FastAPI + SQLAlchemy + psycopg
- `docker-compose.yml`: frontend, backend, and Postgres services

## First-time setup

```bash
copy .env.example .env
docker compose up --build
```

Then open:

- `http://localhost:5173` for the frontend
- `http://localhost:8000/docs` for FastAPI docs

## Daily development

- `docker compose up` starts the full stack
- frontend changes reload through Vite
- backend changes reload through `uvicorn --reload`
- `docker compose down` stops everything

## Helpful commands

```bash
docker compose logs -f
docker compose down -v
docker compose up --build
```

## What this starter proves

- frontend runs
- backend runs
- database runs
- frontend can talk to backend

## Notes

- Use `.env.example` as the shared template and keep real values in `.env`
- The frontend container keeps `node_modules` in a Docker volume so bind mounts do not wipe dependencies
