"""
Tests for AI Tier (Google Gemini Integration).
All LLM and network interactions are strictly mocked (offline).
"""
import pytest
from unittest.mock import patch, MagicMock
from dslc.ai import explain_error, review_code


def test_ai_fallback_when_no_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    err = {
        "code": "E103",
        "message": "Unknown column 'foo'",
        "line": 3,
        "column": 5,
        "source_line": "res = sales | select foo;"
    }
    explanation = explain_error(err, "res = sales | select foo;")
    assert explanation["available"] is False
    assert "AI hints unavailable" in explanation["cause"]

    review = review_code("source", "target", "Python")
    assert review["available"] is False
    assert "AI review unavailable" in review["verdict"]


def test_ai_mocked_explain_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_12345")

    mock_response = MagicMock()
    mock_response.text = '{"cause": "Column foo does not exist in schema.", "suggested_code": "select region", "tip": "Check column names."}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        err = {"code": "E103", "message": "Unknown column 'foo'", "line": 2, "column": 10, "source_line": "select foo"}
        res = explain_error(err, "dummy code")
        assert res["available"] is True
        assert "Column foo does not exist" in res["cause"]
        assert res["suggested_code"] == "select region"
        assert res["tip"] == "Check column names."


def test_ai_mocked_review_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_12345")

    mock_response = MagicMock()
    mock_response.text = '{"verdict": "Pipeline is well structured.", "tips": ["Add index on region", "Consider batching"]}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        res = review_code("source", "target", "SQL")
        assert res["available"] is True
        assert res["verdict"] == "Pipeline is well structured."
        assert len(res["tips"]) == 2


def test_ai_graceful_handling_on_api_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_12345")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("Network timeout")

    with patch("google.genai.Client", return_value=mock_client):
        err = {"code": "E101", "message": "Undefined table", "line": 1, "column": 1, "source_line": "bad"}
        res = explain_error(err, "bad code")
        assert res["available"] is False
        assert "RuntimeError" in res["cause"]
