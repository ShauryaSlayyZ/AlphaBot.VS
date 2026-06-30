import requests
import sqlite3
import os
import json
import time

time.sleep(3) # Wait for server reload if needed

API_BASE = 'http://localhost:8000/api'
DB_PATH = 'sessions.db'

def run_tests():
    print("🚀 Starting Phase 2A SQLite Session Persistence Verification Tests...")

    # Step 1: Create a session
    r = requests.post(f"{API_BASE}/session")
    session_id = r.json()['session_id']
    print(f"✅ Created session: {session_id}")

    # Step 2: Send a query
    query = "Show budget allocated in Gujarat for 2025"
    print(f"💬 Sending query: '{query}'")
    r = requests.post(f"{API_BASE}/query", json={
        'raw_query': query,
        'session_id': session_id
    }, timeout=25)
    query_resp = r.json()
    assert query_resp['status'] == 'success', f"Query failed: {query_resp}"
    print("✅ Query executed successfully")

    # Step 3: Check SQLite database content directly
    assert os.path.exists(DB_PATH), f"sessions.db not found at {DB_PATH}!"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verify session_states
    cursor.execute("SELECT state_json, last_updated FROM session_states WHERE session_id = ?", (session_id,))
    state_row = cursor.fetchone()
    assert state_row is not None, "session_states table has no record for this session_id"
    state_data = json.loads(state_row[0])
    assert state_data['active_metric'] == 'budget_allocated', f"Incorrect active metric: {state_data}"
    print("✅ Verified session_states table holds correct state JSON")

    # Verify query_history
    cursor.execute("SELECT raw_query, resolved_query, blueprint_json FROM query_history WHERE session_id = ?", (session_id,))
    history_row = cursor.fetchone()
    assert history_row is not None, "query_history table has no record for this session_id"
    assert history_row[0] == query, f"Incorrect raw query: {history_row[0]}"
    assert history_row[1] == query, f"Incorrect resolved query: {history_row[1]}"
    bp_data = json.loads(history_row[2])
    assert 'budget_allocated' in bp_data.get('metrics', []), f"Incorrect blueprint: {bp_data}"
    print("✅ Verified query_history table has correct raw, resolved, and blueprint record")

    # Verify session_snapshots
    cursor.execute("SELECT response_json FROM session_snapshots WHERE session_id = ?", (session_id,))
    snapshot_row = cursor.fetchone()
    assert snapshot_row is not None, "session_snapshots table has no record for this session_id"
    snapshot_data = json.loads(snapshot_row[0])
    assert snapshot_data['status'] == 'success', f"Snapshot response status incorrect: {snapshot_data}"
    assert 'results' in snapshot_data, "Snapshot response does not contain results"
    print("✅ Verified session_snapshots table has the latest response snapshot JSON")
    conn.close()

    # Step 4: Verify Rehydration endpoint
    print(f"🔄 Simulating page refresh by fetching session rehydration info...")
    r = requests.get(f"{API_BASE}/session/{session_id}")
    rehyd_data = r.json()
    assert rehyd_data['session_id'] == session_id
    assert rehyd_data['active_metric'] == 'budget_allocated'
    assert rehyd_data['snapshot'] is not None, "Rehydration payload missing latest response snapshot"
    assert rehyd_data['snapshot']['status'] == 'success'
    print("✅ Verified rehydration GET endpoint returns state and latest response snapshot")

    # Step 5: Test follow-up query to check that conversational state context works
    followup = "What about Rajasthan?"
    print(f"💬 Sending follow-up query: '{followup}'")
    r = requests.post(f"{API_BASE}/query", json={
        'raw_query': followup,
        'session_id': session_id
    }, timeout=25)
    followup_resp = r.json()
    assert followup_resp['status'] == 'success'
    ctx = followup_resp.get('conversation_context')
    assert ctx is not None, "Follow-up response missing conversation context"
    assert ctx.get('was_rewritten') is True, "Follow-up was not rewritten using session state"
    print("✅ Verified follow-up query behaves correctly and uses context")

    # Step 6: Test clear session
    print("🗑️ Clearing session...")
    r = requests.delete(f"{API_BASE}/session/{session_id}")
    assert r.json()['status'] == 'cleared'

    # Verify database deletion
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM session_states WHERE session_id = ?", (session_id,))
    assert cursor.fetchone() is None, "State not deleted from session_states table"
    cursor.execute("SELECT 1 FROM query_history WHERE session_id = ?", (session_id,))
    assert cursor.fetchone() is None, "History not deleted from query_history table"
    cursor.execute("SELECT 1 FROM session_snapshots WHERE session_id = ?", (session_id,))
    assert cursor.fetchone() is None, "Snapshot not deleted from session_snapshots table"
    conn.close()
    print("✅ Verified deletion removes records from all three tables")

    print("\n🎉 All Phase 2A SQLite Session Persistence verification tests PASSED! 🎉")

if __name__ == "__main__":
    run_tests()
