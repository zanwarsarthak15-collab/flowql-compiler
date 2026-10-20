"""
Tests for FastAPI Server Endpoints & Static File Serving.
"""
import pytest
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


def test_server_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_server_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "FlowQL" in response.text


def test_server_get_examples():
    response = client.get("/api/examples")
    assert response.status_code == 200
    data = response.json()
    assert "examples" in data
    assert len(data["examples"]) >= 9  # At least 4 valid + 5 invalid


def test_server_compile_python():
    payload = {
        "source": """
        dataset sales(region: str, amount: num) = load "data.csv";
        top = sales | filter amount > 50 | limit 2;
        print top;
        """,
        "target": "python",
        "optimize": True
    }
    response = client.post("/api/compile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "import pandas as pd" in data["target_code"]
    assert "import pandas as pd" in data["generated_code"]
    assert len(data["tokens"]) > 0
    assert len(data["ir"]) > 0
    assert data["ast"] is not None


def test_server_compile_sql():
    payload = {
        "source": """
        dataset sales(region: str, amount: num) = load "data.csv";
        top = sales | filter amount > 50 | limit 2;
        print top;
        """,
        "target": "sql",
        "optimize": True
    }
    response = client.post("/api/compile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "WITH" in data["target_code"]
    assert "WITH" in data["generated_code"]
    assert "LIMIT 2" in data["target_code"]


def test_server_compile_error():
    payload = {
        "source": "top = undefined_table | limit 5; print top;",
        "target": "python",
        "optimize": True
    }
    response = client.post("/api/compile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert len(data["errors"]) > 0
    assert data["errors"][0]["code"] == "E101"


def test_server_explain_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    payload = {
        "error": {
            "code": "E101",
            "message": "Undefined table",
            "line": 1,
            "column": 7,
            "source_line": "top = undefined_table | limit 5;"
        },
        "source": "top = undefined_table | limit 5;"
    }
    response = client.post("/api/explain", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "cause" in data
