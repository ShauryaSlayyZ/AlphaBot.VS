
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import sqlite3

# Import the objects we need to test
from main import app, MetadataRegistry, build_federated_query_parts, Blueprint, POWER_PLANTS

# --- Test Setup and Teardown ---
@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown_for_tests():
    """
    This single fixture handles all setup and teardown to avoid conflicts.
    - It ensures the registry is initialized for all tests.
    - It mocks os.path.exists so no real files are needed.
    """
    with patch('os.path.exists') as mock_exists:
        mock_exists.return_value = True # Pretend all DB files exist
        
        # Manually initialize the registry once for the entire test module
        # This is the critical fix for the unit tests
        print("\n--- Initializing Registry for Test Module ---")
        MetadataRegistry.get_instance() # Get and initialize the singleton instance
        print("--- Registry Initialized ---")
        
        yield # This is where all the tests in the module will run
    
    # No teardown needed as we are mocking file system and registry is in-memory

@pytest.fixture(scope="function")
def client():
    """Provides a new TestClient for each integration test."""
    with TestClient(app) as c:
        yield c

# --- Unit Tests for Logic ---
# These tests now run against a pre-initialized registry.
def test_build_federated_query_parts_simple():
    bp = Blueprint(metrics=["revenue"])
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert where == ""
    assert metrics == ["revenue"]
    assert params == ()

def test_build_federated_query_parts_with_filters():
    bp = Blueprint(metrics=["profit"], filters=[{"column": "region", "value": "north"}])
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert where == "region = ?"
    assert metrics == ["profit"]
    assert params == ("north",)

def test_build_federated_query_parts_with_timeframe():
    bp = Blueprint(metrics=["headcount"], timeframe={"type": "year", "value": "2025"})
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert "strftime('%Y', record_date) = ?" in where
    assert metrics == ["headcount"]
    assert params == ("2025",)

# --- Integration Tests for API Endpoint ---
@patch('main.run_query_on_single_db')
def test_total_revenue_query(mock_run_query, client):
    mock_run_query.return_value = [{"revenue": 1000}]
    payload = {"raw_query": "what is total revenue", "blueprint": {"metrics": ["revenue"]}}
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["results"][0]["revenue"] == 1000 * len(POWER_PLANTS)

@patch('main.run_query_on_single_db')
def test_filtered_headcount_query(mock_run_query, client):
    mock_run_query.return_value = [{"headcount": 10}]
    payload = {
        "raw_query": "headcount for digital",
        "blueprint": {"metrics": ["headcount"], "filters": [{"column": "department", "value": "digital"}]}
    }
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["results"][0]["headcount"] == 10 * len(POWER_PLANTS)

@patch('main.run_query_on_single_db')
def test_multi_metric_breakdown_query(mock_run_query, client):
    mock_run_query.return_value = [{
        "revenue": 900000.0, "profit": 100000.0, "expenses": 800000.0,
        "headcount": 42, "salary": 2192851.91, "tax_liability": 20745.16,
        "asset_value": 2251840.27, "operating_cost": 637608.24,
        "marketing_spend": 45036.81, "customer_count": 2885
    }]
    payload = {
        "raw_query": "what is the breakdown of revenue, profit, expenses, headcount, salary, customer count in sales department in 2026-08-13 19:00:00 of grand_gulf in south region",
        "blueprint": {
            "operation": "BREAKDOWN",
            "metrics": ["revenue", "profit", "expenses", "headcount", "salary", "customer_count"],
            "filters": [
                {"column": "department", "value": "sales"},
                {"column": "plant", "value": "grand_gulf"},
                {"column": "region", "value": "south"}
            ],
            "timeframe": {"type": "timestamp", "value": "2026-08-13 19:00:00"}
        }
    }
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert len(data["results"]) == 1
    assert data["results"][0]["revenue"] == 900000.0
    assert data["results"][0]["profit"] == 100000.0
    assert data["results"][0]["expenses"] == 800000.0
    assert data["results"][0]["headcount"] == 42
    assert data["results"][0]["salary"] == 2192851.91
    assert data["results"][0]["customer_count"] == 2885
    assert data["plants_queried"] == 1

def test_health_check(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "online"}

def test_deterministic_parser_word_boundaries_and_top_n():
    from main import parse_query_deterministically
    
    # 1. Word boundary check ('through' should not match 'hr')
    res_through = parse_query_deterministically("marketing spend breakdown by department at palo verde from 2022 through 2026")
    assert res_through is not None
    filters = res_through["blueprint"].filters
    depts = [f["value"] for f in filters if f["column"] == "department"]
    assert "hr" not in depts
    
    # 2. top_n subject rank check ('top plants' should have 'plant' as comparison dimension)
    res_top = parse_query_deterministically("top plants by profit in sales department from 2023 to 2026")
    assert res_top is not None
    assert res_top["blueprint"].comparison == {"type": "plant"}
