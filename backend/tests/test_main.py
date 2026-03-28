from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_hello_returns_expected_message():
    response = client.get("/api/hello")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from FastAPI"}


def test_db_health_returns_expected_message(monkeypatch):
    class FakeResult:
        def fetchone(self):
            return ("Postgres is connected",)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query):
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "engine", FakeEngine())

    response = client.get("/api/health/db")

    assert response.status_code == 200
    assert response.json() == {"message": "Postgres is connected"}

