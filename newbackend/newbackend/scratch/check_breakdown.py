import httpx
import json

url = "http://localhost:8000/api/query"
payload = {
    "raw_query": "what is the breakdown of sales department in 2026-08-13 19:00:00 of grand_gulf in south region",
    "blueprint": {
        "operation": "BREAKDOWN",
        "metrics": [],  # Leave empty to test new default logic!
        "filters": [
            {"column": "department", "value": "sales"},
            {"column": "plant", "value": "grand_gulf"},
            {"column": "region", "value": "south"}
        ],
        "timeframe": {"type": "timestamp", "value": "2026-08-13 19:00:00"},
        "comparison": None,
        "breakdown_by": None
    },
    "parsing_metadata": {
        "client_processing_time_ms": 0.5,
        "fallback_required": False
    }
}

try:
    resp = httpx.post(url, json=payload, timeout=5.0)
    print("STATUS CODE:", resp.status_code)
    print("RESPONSE:")
    print(json.dumps(resp.json(), indent=2))
except Exception as e:
    print("ERROR:", e)
