import os
import sqlite3
import pytest
import threading
import time
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import (
    app,
    Blueprint,
    ConversationStateManager,
    calculate_blueprint_hash,
    calculate_blueprint_delta,
    estimate_routing_costs,
    calculate_reuse_score
)
from backend.cache import SessionResultCacheManager

TEST_DB_PATH = "backend/test_phase2_sessions.db"

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
    
    # Initialize cache manager catalog
    cache_mgr = SessionResultCacheManager.get_instance()
    cache_mgr.catalog.clear()
    cache_mgr.session_activity.clear()
    
    yield
    
    # Cleanup after test
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

# 1. Test Dynamic Catalog Table Migrations and Schema Creation
def test_catalog_table_creation():
    csm = ConversationStateManager.get_instance()
    conn = csm._get_conn()
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_catalog'")
    row = cursor.fetchone()
    assert row is not None, "cache_catalog table should be created by _init_db()"
    
    # Check table columns
    cursor.execute("PRAGMA table_info(cache_catalog)")
    cols = {r[1]: r[2] for r in cursor.fetchall()}
    assert "node_id" in cols
    assert "session_id" in cols
    assert "parent_id" in cols
    assert "blueprint_hash" in cols
    assert "metrics" in cols
    assert "filters" in cols
    assert "dimensions" in cols
    assert "timeframe" in cols
    assert "cache_type" in cols
    assert "row_count" in cols
    assert "memory_size" in cols
    assert "db_version_hash" in cols
    
    # Verify index exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cache_catalog'")
    indexes = [r[0] for r in cursor.fetchall()]
    assert "idx_catalog_session" in indexes
    assert "idx_catalog_hash" in indexes
    conn.close()

# 2. Test Thread-Local Connection Isolation
def test_thread_local_connection_isolation():
    cache_mgr = SessionResultCacheManager.get_instance()
    
    conn_main = cache_mgr._get_connection()
    assert conn_main is not None
    
    thread_conns = []
    def thread_worker():
        conn_thread = cache_mgr._get_connection()
        thread_conns.append(conn_thread)
        
    t1 = threading.Thread(target=thread_worker)
    t2 = threading.Thread(target=thread_worker)
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    assert len(thread_conns) == 2
    assert thread_conns[0] is not thread_conns[1], "Each thread must have its own DuckDB connection instance"
    assert thread_conns[0] is not conn_main, "Thread-local connection must be isolated from the main thread connection"

# 3. Test Composite Version Validation and Stale Invalidations
def test_composite_version_validation():
    cache_mgr = SessionResultCacheManager.get_instance()
    
    # Dummy list of plants
    plants = ["vogtle", "hinkley_point"]
    
    # Mock sqlite3.connect to yield dynamic PRAGMA data_version values
    with patch("sqlite3.connect") as mock_connect:
        mock_conn1 = MagicMock()
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchone.return_value = (5,)  # data_version = 5
        mock_conn1.cursor.return_value = mock_cursor1
        
        mock_connect.return_value = mock_conn1
        
        hash1 = cache_mgr.get_composite_version_hash(plants)
        
        # Second version lookup with same value
        hash2 = cache_mgr.get_composite_version_hash(plants)
        assert hash1 == hash2, "Composite hash should be identical for unchanged data_version values"
        
        # Third version lookup with modified data_version value
        mock_cursor2 = MagicMock()
        mock_cursor2.fetchone.return_value = (6,)  # data_version changes to 6
        mock_conn2 = MagicMock()
        mock_conn2.cursor.return_value = mock_cursor2
        mock_connect.return_value = mock_conn2
        
        cache_mgr._version_cache.clear()
        hash3 = cache_mgr.get_composite_version_hash(plants)
        assert hash1 != hash3, "Composite hash must change when database version changes"

def test_memory_governance_eviction():
    cache_mgr = SessionResultCacheManager.get_instance()
    orig_soft = cache_mgr.SOFT_LIMIT_BYTES
    orig_hard = cache_mgr.HARD_LIMIT_BYTES
    try:
        # Set extremely low limits for testing purposes
        cache_mgr.SOFT_LIMIT_BYTES = 500
        cache_mgr.HARD_LIMIT_BYTES = 1000
        
        session_1 = "sess-1"
        session_2 = "sess-2"
        session_3 = "sess-3"
        
        dummy_rows_1 = [{"col1": 1, "col2": "a"}] * 3  # cells = 6 -> est_size = 600 bytes
        dummy_rows_2 = [{"col1": 2, "col2": "b"}] * 3  # cells = 6 -> est_size = 600 bytes
        dummy_rows_3 = [{"col1": 3, "col2": "c"}] * 3  # cells = 6 -> est_size = 600 bytes
        
        # Save cache 1: Size ~600 bytes (within Hard Limit, but triggers Soft Limit warning/eviction)
        cache_mgr.save_cache(session_1, 101, dummy_rows_1, "hash-1")
        assert cache_mgr.has_cache(session_1, 101)
        
        # Save cache 2: Size projected to be 1200 bytes. Exceeds Hard Limit (1000 bytes).
        # This should trigger synchronous eviction of session_1 (since it is the oldest).
        cache_mgr.save_cache(session_2, 102, dummy_rows_2, "hash-2")
        
        # Session 1 should be evicted synchronously
        assert not cache_mgr.has_cache(session_1, 101), "Session 1 must be evicted to free memory for Session 2"
        assert cache_mgr.has_cache(session_2, 102)
    finally:
        cache_mgr.SOFT_LIMIT_BYTES = orig_soft
        cache_mgr.HARD_LIMIT_BYTES = orig_hard

# 5. Test Ancestor Lineage Climbing and Routing Logic
def test_ancestor_climbing_and_routing():
    client = TestClient(app)
    csm = ConversationStateManager.get_instance()
    cache_mgr = SessionResultCacheManager.get_instance()
    
    # Mock external query runner so tests are fast and run locally
    with patch("backend.main.run_query_on_single_db") as mock_run_query:
        # Initial query response
        mock_run_query.return_value = [{"revenue": 50000, "plant": "hinkley_point", "record_date": "2025-01-01"}]
        
        # Step A: First query (Turn 1) -> Global query, not cached but saved to query history
        resp1 = client.post("/api/query", json={
            "raw_query": "revenue for Hinkley Point",
            "session_id": "sess-climb",
            "blueprint": {
                "metrics": ["revenue"],
                "filters": [{"column": "plant", "value": "hinkley_point"}]
            }
        })
        assert resp1.status_code == 200
        d1 = resp1.json()
        assert d1["status"] == "success"
        
        # Verify query was saved to history
        last_hist = csm.get_last_query_history("sess-climb")
        assert last_hist is not None
        parent_id = last_hist["id"]
        
        dummy_parent_rows = [
            {"revenue": 50000, "plant": "hinkley_point", "record_date": "2025-01-01", "state": "Gujarat", "location": "Hinkley point", "project_type": "Solar", "department": "Operations", "fy_year": 2025},
            {"revenue": 30000, "plant": "hinkley_point", "record_date": "2025-02-01", "state": "Rajasthan", "location": "Hinkley point", "project_type": "Solar", "department": "Operations", "fy_year": 2025}
        ]
        
        # Set composite version hash
        ver_hash = cache_mgr.get_composite_version_hash(["hinkley_point"])
        cache_mgr.save_cache("sess-climb", parent_id, dummy_parent_rows, ver_hash)
        
        csm.save_cache_catalog_entry(
            node_id=parent_id,
            session_id="sess-climb",
            parent_id=None,
            blueprint_hash=last_hist["blueprint_hash"],
            metrics=["revenue"],
            filters=[{"column": "plant", "value": "hinkley_point"}],
            dimensions=[],
            timeframe=None,
            cache_type="RAW",
            row_count=len(dummy_parent_rows),
            memory_size=cache_mgr._estimate_rows_size(dummy_parent_rows),
            db_version_hash=ver_hash
        )
        
        # Step B: Execute subset query (Turn 2) -> Should route locally to cached parent
        resp2 = client.post("/api/query", json={
            "raw_query": "what about Gujarat?",
            "session_id": "sess-climb",
            "blueprint": {
                "metrics": ["revenue"],
                "filters": [
                    {"column": "plant", "value": "hinkley_point"},
                    {"column": "state", "value": "Gujarat"}
                ]
            }
        })
        
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2["metadata"]["cache_hit"] is True, "Turn 2 query should be cache_hit"
        assert d2["metadata"]["cache_type"] == "duckdb_local"
        assert len(d2["results"]) == 1
        assert d2["results"][0]["state"] == "Gujarat"
        
        # Step C: Evict immediate parent cache but keep grandparent query history
        # (simulates cache eviction while retaining session lineage)
        child_id = csm.get_last_query_history("sess-climb")["id"]
        cache_mgr.drop_node_cache("sess-climb", child_id)  # evict direct parent cache
        csm.delete_cache_catalog_entry("sess-climb", child_id)
        
        # Step D: Execute a Turn 3 query -> Should climb up past evicted parent to grandparent ancestor
        resp3 = client.post("/api/query", json={
            "raw_query": "what about Rajasthan?",
            "session_id": "sess-climb",
            "blueprint": {
                "metrics": ["revenue"],
                "filters": [
                    {"column": "plant", "value": "hinkley_point"},
                    {"column": "state", "value": "Rajasthan"}
                ]
            }
        })
        
        assert resp3.status_code == 200
        d3 = resp3.json()
        assert d3["metadata"]["cache_hit"] is True, "Turn 3 query should climb to ancestor and resolve as cache_hit"
        assert d3["metadata"]["cache_type"] == "duckdb_local"
        assert len(d3["results"]) == 1
        assert d3["results"][0]["state"] == "Rajasthan"
