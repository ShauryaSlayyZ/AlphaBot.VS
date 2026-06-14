import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

payload = {
    "raw_query": "what is the breakdown graph of palo_verde in year 2026",
    "blueprint": {
        "operation": "GRAPH",
        "metrics": [],
        "filters": [],
        "timeframe": {
            "type": "year",
            "value": "2026"
        },
        "comparison": None,
        "breakdown_by": None
    },
    "parsing_metadata": {
        "client_processing_time_ms": 0.5,
        "fallback_required": True,
        "unknown_tokens": ["palo_verde"]
    }
}

try:
    print("Sending query to TestClient...")
    response = client.post("/api/query", json=payload)
    print("Response Status:", response.status_code)
    print("Response JSON:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    import traceback
    print("Exception occurred:")
    traceback.print_exc()
