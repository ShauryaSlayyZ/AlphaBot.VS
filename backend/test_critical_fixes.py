import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from main import app, MetadataRegistry, POWER_PLANTS

@pytest.fixture(scope="module", autouse=True)
def setup_mock_metadata():
    registry = MetadataRegistry.get_instance()
    registry.metrics = {
        "revenue": {"column": "revenue", "type": "NUMERIC"},
        "budget_allocated": {"column": "budget_allocated", "type": "NUMERIC"},
        "completion_percentage": {"column": "completion_percentage", "type": "NUMERIC"},
        "delay_days": {"column": "delay_days", "type": "NUMERIC"}
    }
    registry.categoricals = {
        "location": {"values": ["Hinkley point", "Vogtle", "Darlington", "Gujarat"]},
        "state": {"values": ["Gujarat", "Rajasthan"]},
        "project_type": {"values": ["Solar", "Wind", "Hybrid"]},
        "fy_year": {"values": [2023, 2024, 2025, 2026]}
    }
    registry._initialized = True
    yield

@pytest.fixture(scope="function")
def client():
    with TestClient(app) as c:
        yield c

def test_zero_trust_unresolved_gibberish(client):
    # Fix 2: Unresolved entities should trigger clarification_required and NOT execute SQL or cached results
    payload = {
        "raw_query": "show revenue of xyzabc",
        "blueprint": None
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "clarification_required"
    assert "unrecognized entities: xyzabc" in data["message"]
    assert data["results"] == []

def test_plural_nouns_allowed(client):
    # Verified plural nouns are recognized as known/stopwords and NOT blocked by Zero Trust
    payload = {
        "raw_query": "compare revenue across states",
        "blueprint": None
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Should not block on "states"
    assert data["status"] != "clarification_required"

@patch('main.call_ollama_fallback')
@patch('main.run_query_on_single_db')
def test_llm_mode_cache_bypass(mock_run_query, mock_ollama, client):
    # Fix 3: LLM Mode (force_llm=True) bypasses all caching layers
    mock_run_query.return_value = [{"revenue": 5000}]
    from main import Blueprint
    mock_ollama.return_value = Blueprint(metrics=["revenue"])
    
    payload = {
        "raw_query": "force llm query",
        "blueprint": None,
        "force_llm": True
    }
    
    # First request
    r1 = client.post("/api/query", json=payload)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["metadata"]["cache_hit"] is False
    assert d1["metadata"]["parser_used"] == "llm"
    assert d1["metadata"]["mode"] == "llm_only"
    
    # Second identical request (cache should be bypassed)
    r2 = client.post("/api/query", json=payload)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["metadata"]["cache_hit"] is False
    assert d2["metadata"]["parser_used"] == "llm"
    assert d2["metadata"]["mode"] == "llm_only"
