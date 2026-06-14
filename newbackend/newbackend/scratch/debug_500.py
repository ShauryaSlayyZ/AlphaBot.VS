import sys
import os
import traceback
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def send_query(raw_query, blueprint=None, force_llm=False, unknown_tokens=None):
    payload = {
        "raw_query": raw_query,
        "blueprint": blueprint,
        "force_llm": force_llm,
        "parsing_metadata": {
            "client_processing_time_ms": 0.5,
            "fallback_required": force_llm or (unknown_tokens is not None),
            "unknown_tokens": unknown_tokens or []
        }
    }
    response = client.post("/api/query", json=payload)
    return response.status_code, response.json()

if __name__ == "__main__":
    print("=== Testing Query 3 ===")
    try:
        status, res = send_query(
            "revenue of palo_verde in year 2030",
            blueprint={
                "operation": "SUM",
                "metrics": ["revenue"],
                "filters": [],
                "timeframe": {"type": "year", "value": "2030"}
            },
            unknown_tokens=["palo_verde"]
        )
        print(f"Status: {status}")
        print(f"Result: {res}")
    except Exception:
        traceback.print_exc()

    print("\n=== Testing Query 4 ===")
    try:
        status, res = send_query(
            "revenue of paloverde in year 2025",
            blueprint={
                "operation": "SUM",
                "metrics": ["revenue"],
                "filters": [],
                "timeframe": {"type": "year", "value": "2025"}
            },
            unknown_tokens=["paloverde"]
        )
        print(f"Status: {status}")
        print(f"Result: {res}")
    except Exception:
        traceback.print_exc()
