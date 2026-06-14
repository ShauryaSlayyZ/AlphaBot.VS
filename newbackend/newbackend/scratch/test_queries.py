import requests
import json

BASE_URL = "http://localhost:8000"

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
    try:
        response = requests.post(f"{BASE_URL}/api/query", json=payload)
        return response.status_code, response.json()
    except Exception as e:
        return 500, {"error": str(e)}

if __name__ == "__main__":
    print("=== Testing System with Robustness & Edge Cases ===")

    print("\nQuery 1: Breakdown graph of palo_verde in 2026 (Direct Site Routing + Recovery)")
    # 'palo_verde' is marked as an unknown token to simulate a failed metadata sync recovery
    status, res = send_query(
        "what is the breakdown graph of palo_verde in year 2026",
        blueprint={
            "operation": "GRAPH",
            "metrics": [],
            "filters": [],
            "timeframe": {"type": "year", "value": "2026"}
        },
        unknown_tokens=["palo_verde"]
    )
    print(f"Status: {status}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print(f"Sources queried: {res.get('metadata', {}).get('sources')}")
    print("Results sample:")
    print(json.dumps(res.get('results', [])[:3], indent=2))

    print("\nQuery 2: Dual filter collision (Solar and Wind) in 2025 (IN clause builder)")
    # Blueprint contains multiple filters on 'project_type'
    status, res = send_query(
        "what is the revenue of solar and wind in year 2025",
        blueprint={
            "operation": "SUM",
            "metrics": ["revenue"],
            "filters": [
                {"column": "project_type", "value": "Solar"},
                {"column": "project_type", "value": "Wind"}
            ],
            "timeframe": {"type": "year", "value": "2025"}
        }
    )
    print(f"Status: {status}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print("Results sample:")
    print(json.dumps(res.get('results'), indent=2))

    print("\nQuery 3: Out-of-bounds timeframe validation error (2030 Year Guard)")
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
    print(f"Response Status: {res.get('status')}")
    print(f"Message: {res.get('message')}")

    print("\nQuery 4: Levenshtein typo recovery ('paloverde' -> 'palo_verde')")
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
    print(f"SQL Generated: {res.get('sql_query')}")
    print(f"Sources queried: {res.get('metadata', {}).get('sources')}")

    print("\nQuery 5: Average aggregation fallback on rate column (completion_percentage)")
    status, res = send_query(
        "what is completion rate of solar in year 2026",
        blueprint={
            "operation": "SUM",
            "metrics": ["completion_percentage"],
            "filters": [{"column": "project_type", "value": "Solar"}],
            "timeframe": {"type": "year", "value": "2026"}
        }
    )
    print(f"Status: {status}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print("Results sample:")
    print(json.dumps(res.get('results'), indent=2))
