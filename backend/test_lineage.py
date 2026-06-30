import os
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from backend.main import (
    app,
    Blueprint,
    calculate_blueprint_hash,
    calculate_blueprint_delta,
    ConversationStateManager,
    QueryBlueprintPayload
)

# Use a test-specific database path to avoid polluting the development DB
TEST_DB_PATH = "backend/test_sessions.db"

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Sets up a clean test sessions database before each test."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
            
    # Override DB_PATH in ConversationStateManager
    monkeypatch.setattr(ConversationStateManager, "DB_PATH", TEST_DB_PATH)
    # Clear singleton instance to force re-initialization
    ConversationStateManager._instance = None
    yield
    
    # Cleanup after test
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

def test_calculate_blueprint_hash():
    """Verify that blueprint hashes are stable, deterministic, and order-independent."""
    bp1 = Blueprint(
        operation="SUM",
        metrics=["revenue", "profit"],
        filters=[{"column": "state", "value": "Gujarat"}, {"column": "year", "value": "2025"}]
    )
    bp2 = Blueprint(
        operation="SUM",
        metrics=["profit", "revenue"],  # different metric order
        filters=[{"column": "year", "value": "2025"}, {"column": "state", "value": "Gujarat"}]  # different filter order
    )
    
    hash1 = calculate_blueprint_hash(bp1)
    hash2 = calculate_blueprint_hash(bp2)
    assert hash1 == hash2
    assert len(hash1) == 32  # MD5 hex digest length

def test_calculate_blueprint_delta():
    """Test all delta engine operations: metric shifts, filter additions/removals/modifications, limits, and sorts."""
    # Base parent blueprint
    parent = Blueprint(
        operation="SUM",
        metrics=["revenue"],
        filters=[{"column": "state", "value": "Gujarat"}],
        timeframe={"type": "year", "value": "2025"},
        limit=10,
        sort_asc=False
    )
    
    # Test ADD_FILTER and MODIFY_FILTER
    child1 = Blueprint(
        operation="SUM",
        metrics=["revenue"],
        filters=[
            {"column": "state", "value": "Gujarat"},
            {"column": "year", "value": "2026"},      # ADD_FILTER
            {"column": "department", "value": "Solar"} # ADD_FILTER
        ],
        timeframe={"type": "year", "value": "2025"},
        limit=10,
        sort_asc=False
    )
    delta1 = calculate_blueprint_delta(parent, child1)
    actions1 = delta1["actions"]
    assert len(actions1) == 2
    types = {a["type"] for a in actions1}
    assert "ADD_FILTER" in types
    
    # Test CHANGE_METRIC, REMOVE_FILTER, CHANGE_TIMEFRAME, CHANGE_LIMIT, CHANGE_SORT
    child2 = Blueprint(
        operation="AVERAGE", # CHANGE_OPERATION
        metrics=["profit"],  # CHANGE_METRIC
        filters=[],          # REMOVE_FILTER (state=Gujarat removed)
        timeframe={"type": "year", "value": "2026"}, # CHANGE_TIMEFRAME
        limit=5,             # CHANGE_LIMIT
        sort_asc=True,       # CHANGE_SORT
        comparison={"type": "plant"} # CHANGE_BREAKDOWN
    )
    delta2 = calculate_blueprint_delta(parent, child2)
    actions2 = delta2["actions"]
    types2 = {a["type"] for a in actions2}
    
    assert "CHANGE_OPERATION" in types2
    assert "CHANGE_METRIC" in types2
    assert "REMOVE_FILTER" in types2
    assert "CHANGE_TIMEFRAME" in types2
    assert "CHANGE_LIMIT" in types2
    assert "CHANGE_SORT" in types2
    assert "CHANGE_BREAKDOWN" in types2

def test_database_auto_migration():
    """Verify that ConversationStateManager migrates an old database schema successfully."""
    # Step 1: Create an old-style SQLite database
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            raw_query TEXT,
            resolved_query TEXT,
            blueprint_json TEXT,
            timestamp REAL
        )
    """)
    # Insert a dummy record
    cursor.execute(
        "INSERT INTO query_history (session_id, raw_query, resolved_query, blueprint_json, timestamp) VALUES (?, ?, ?, ?, ?)",
        ("test_session", "initial query", "initial query", "{}", 12345.6)
    )
    conn.commit()
    conn.close()
    
    # Step 2: Initialize the ConversationStateManager (should run migrations dynamically)
    csm = ConversationStateManager.get_instance()
    
    # Step 3: Query table columns to ensure new columns and indexes were added safely
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(query_history)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    assert "parent_id" in columns
    assert "depth" in columns
    assert "blueprint_hash" in columns
    assert "delta_json" in columns
    assert "is_subset" in columns
    
    # Verify the dummy record still exists intact
    history = csm.get_last_query_history("test_session")
    assert history is not None
    assert history["raw_query"] == "initial query"
    assert history["parent_id"] is None
    assert history["depth"] == 0

def test_lineage_and_depth_tracking():
    """Test parent-child propagation, depth incrementation, and subset detection."""
    csm = ConversationStateManager.get_instance()
    session_id = "sess_lineage_test"
    
    bp1 = Blueprint(metrics=["revenue"], operation="SUM")
    bp2 = Blueprint(metrics=["revenue"], operation="SUM", filters=[{"column": "state", "value": "Gujarat"}])
    bp3 = Blueprint(metrics=["revenue"], operation="SUM", filters=[{"column": "state", "value": "Gujarat"}, {"column": "year", "value": "2025"}])
    
    # Insert Turn 1
    id1 = csm.add_query_history(session_id, "revenue", "revenue", bp1, parent_id=None, depth=0, blueprint_hash="hash1", delta_json="{}")
    assert id1 is not None
    
    # Insert Turn 2 (with parent reference)
    delta2 = calculate_blueprint_delta(bp1, bp2)
    is_sub2 = 1 # strict subset
    id2 = csm.add_query_history(session_id, "revenue Gujarat", "revenue Gujarat", bp2, parent_id=id1, depth=1, blueprint_hash="hash2", delta_json=json.dumps(delta2), is_subset=is_sub2)
    
    # Insert Turn 3
    delta3 = calculate_blueprint_delta(bp2, bp3)
    is_sub3 = 1
    id3 = csm.add_query_history(session_id, "revenue Gujarat 2025", "revenue Gujarat 2025", bp3, parent_id=id2, depth=2, blueprint_hash="hash3", delta_json=json.dumps(delta3), is_subset=is_sub3)
    
    # Retrieve and verify Turn 3
    last = csm.get_last_query_history(session_id)
    assert last["id"] == id3
    assert last["parent_id"] == id2
    assert last["depth"] == 2
    assert last["is_subset"] == 1
    assert "ADD_FILTER" in last["delta_json"]

def test_client_parent_id_override_branching():
    """Test client-driven parent_id override, verifying the lineage branching mechanism."""
    client = TestClient(app)
    session_id = "sess_branch_test"
    
    # 1. First query: Revenue
    bp_root = Blueprint(metrics=["revenue"], operation="SUM")
    res1 = client.post("/api/query", json={
        "raw_query": "Revenue",
        "blueprint": bp_root.model_dump(),
        "session_id": session_id
    })
    assert res1.status_code == 200
    
    # Retrieve first query ID
    csm = ConversationStateManager.get_instance()
    q1 = csm.get_last_query_history(session_id)
    id1 = q1["id"]
    
    # 2. Second query: Revenue Gujarat (parent defaults to id1)
    bp_child1 = Blueprint(metrics=["revenue"], operation="SUM", filters=[{"column": "state", "value": "Gujarat"}])
    res2 = client.post("/api/query", json={
        "raw_query": "Revenue Gujarat",
        "blueprint": bp_child1.model_dump(),
        "session_id": session_id
    })
    assert res2.status_code == 200
    q2 = csm.get_last_query_history(session_id)
    id2 = q2["id"]
    assert q2["parent_id"] == id1
    assert q2["depth"] == 1
    
    # 3. Third query: Revenue Rajasthan (branched from id1 instead of id2)
    bp_child2 = Blueprint(metrics=["revenue"], operation="SUM", filters=[{"column": "state", "value": "Rajasthan"}])
    res3 = client.post("/api/query", json={
        "raw_query": "Revenue Rajasthan",
        "blueprint": bp_child2.model_dump(),
        "session_id": session_id,
        "parent_id": id1  # Explicit override!
    })
    assert res3.status_code == 200
    
    # Verify branching in database
    conn = csm._get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT parent_id, depth, delta_json FROM query_history ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    parent_id, depth, delta_json = row
    assert parent_id == id1
    assert depth == 1
    delta = json.loads(delta_json)
    assert delta["actions"][0]["type"] == "ADD_FILTER"
    assert delta["actions"][0]["value"] == "Rajasthan"

def test_api_lineage_visualization():
    """Verify that /api/session/{session_id}/lineage returns complete and correct DAG data."""
    client = TestClient(app)
    session_id = "sess_viz_test"
    
    # Run a chain of 3 queries
    client.post("/api/query", json={
        "raw_query": "Revenue",
        "blueprint": Blueprint(metrics=["revenue"], operation="SUM").model_dump(),
        "session_id": session_id
    })
    client.post("/api/query", json={
        "raw_query": "Revenue Gujarat",
        "blueprint": Blueprint(metrics=["revenue"], operation="SUM", filters=[{"column": "state", "value": "Gujarat"}]).model_dump(),
        "session_id": session_id
    })
    
    # Query lineage endpoint
    res = client.get(f"/api/session/{session_id}/lineage")
    assert res.status_code == 200
    data = res.json()
    assert "lineage" in data
    lineage = data["lineage"]
    assert len(lineage) == 2
    
    # Validate node structures
    node1 = lineage[0]
    node2 = lineage[1]
    assert node1["parent_id"] is None
    assert node1["depth"] == 0
    
    assert node2["parent_id"] == node1["node_id"]
    assert node2["depth"] == 1
    assert len(node2["delta"]["actions"]) == 1
    assert node2["delta"]["actions"][0]["type"] == "ADD_FILTER"
    assert node2["delta"]["actions"][0]["field"] == "state"
    assert node2["delta"]["actions"][0]["value"] == "Gujarat"
