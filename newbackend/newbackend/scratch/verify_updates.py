import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def send_query(raw_query, blueprint=None, force_llm=False):
    payload = {
        "raw_query": raw_query,
        "blueprint": blueprint,
        "force_llm": force_llm
    }
    response = client.post("/api/query", json=payload)
    return response.status_code, response.json()

if __name__ == "__main__":
    print("=== Running Local TestClient Verification ===")

    print("\nCase 1: Standard total revenue query (Fixed NameError)")
    status, res = send_query("what is the total revenue", {
        "operation": "SUM",
        "metrics": ["revenue"],
        "filters": [],
        "timeframe": None,
        "comparison": None
    })
    print(f"Status: {status}")
    print(f"Results: {json.dumps(res, indent=2)}")

    print("\nCase 2: Single date filter (Fixed NameError + timeframe mapping)")
    status, res = send_query("what is the revenue in 2025", {
        "operation": "SUM",
        "metrics": ["revenue"],
        "filters": [],
        "timeframe": {"type": "year", "value": "2025"},
        "comparison": None
    })
    print(f"Status: {status}")
    print(f"Results: {json.dumps(res, indent=2)}")

    print("\nCase 6: Forced LLM mode with valid query (Fixed LLM-Fallback-Revert)")
    # Since Ollama is offline in this test, LLM fallback will return no metrics.
    # The system should fall back to the client-parsed blueprint and succeed (Status 200)
    # instead of throwing "clarification_required"!
    status, res = send_query("revenue in 2023", {
        "operation": "SUM",
        "metrics": ["revenue"],
        "filters": [],
        "timeframe": {"type": "year", "value": "2023"},
        "comparison": None
    }, force_llm=True)
    print(f"Status: {status}")
    print(f"Results: {json.dumps(res, indent=2)}")
