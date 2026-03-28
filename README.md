# forecastapp

Hello world monorepo using React, FastAPI, and PostgreSQL with Docker Compose.

## Stack

- `frontend/`: React + Vite
- `backend/`: FastAPI + SQLAlchemy + psycopg
- `docker-compose.yml`: frontend, backend, and Postgres services

## Run locally

```bash
docker compose up --build
```

Then open:

- `http://localhost:5173` for the frontend
- `http://localhost:8000/docs` for FastAPI docs

## What this starter proves

- frontend runs
- backend runs
- database runs
- frontend can talk to backend

