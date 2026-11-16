"""HTTP API tests (no network to real providers)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from medagent.serve.api import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Med Evidence Agent" in response.text


def test_research_rejects_short_question():
    response = client.post("/research", json={"question": "hi"})
    assert response.status_code == 422