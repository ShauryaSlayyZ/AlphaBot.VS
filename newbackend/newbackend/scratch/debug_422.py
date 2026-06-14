import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

payload = {
    "raw_query": "revenue between 2023",
    "blueprint": {
        "operation": None,
        "metrics": ["revenue"],
        "filters": [],
        "timeframe": {"type": "year", "value": "2023"},
        "timeframes": [{"type": "year", "value": "2023"}],
        "comparison": None,
        "breakdown_by": None
    },
    "parsing_metadata": {
        "client_processing_time_ms": 0.5,
        "fallback_required": True
    }
}

response = client.post("/api/query", json=payload)
print("STATUS CODE:", response.status_code)
try:
    print("RESPONSE JSON:", json.dumps(response.json(), indent=2))
except Exception:
    print("RESPONSE TEXT:", response.text)
