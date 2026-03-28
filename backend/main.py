import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@db:5432/appdb",
)

app = FastAPI(title="Forecast App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(DATABASE_URL, future=True)


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello from FastAPI"}


@app.get("/api/health/db")
def db_health() -> dict[str, str]:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 'Postgres is connected' AS message;"))
        row = result.fetchone()

    message = row[0] if row else "Database check failed"
    return {"message": message}

