
import httpx
import json
import asyncio
from unittest.mock import patch

print("--- SCRIPT START ---")

API_URL = "http://localhost:8000/api/query"
GROUND_TRUTH_FILE = "ground_truth.json"

TEST_CASES = [
    {
        "name": "Total Profit for 2025",
        "query": "what is the total profit in 2025",
        "truth_key": "total_profit_2025",
        "response_key": "profit",
        "blueprint_override": {"metrics": ["profit"], "filters": [], "timeframe": {"type": "year", "value": "2025"}}
    },
    {
        "name": "Total Revenue for North in 2024",
        "query": "total revenue for north region in 2024",
        "truth_key": "total_revenue_north_2024",
        "response_key": "revenue",
        "blueprint_override": {"metrics": ["revenue"], "filters": [{"column": "region", "value": "north"}], "timeframe": {"type": "year", "value": "2024"}}
    },
    {
        "name": "Total Headcount for Digital",
        "query": "what is the total headcount for the digital department",
        "truth_key": "total_headcount_digital",
        "response_key": "headcount",
        "blueprint_override": {"metrics": ["headcount"], "filters": [{"column": "department", "value": "digital"}], "timeframe": None}
    },
    {
        "name": "Total Marketing Spend for Finance in 2023",
        "query": "give me the marketing_spend of finance in fy2023",
        "truth_key": "total_marketing_spend_finance_2023",
        "response_key": "marketing_spend",
        "blueprint_override": {"metrics": ["marketing_spend"], "filters": [{"column": "department", "value": "finance"}], "timeframe": {"type": "year", "value": "2023"}}
    }
]

async def run_single_test(client, test_case, ground_truth):
    """Sends a single query to the API and compares the result."""
    print(f"Running test: {test_case['name']}...")
    
    blueprint_to_send = test_case.get("blueprint_override")
    payload = {
        "raw_query": test_case["query"],
        "blueprint": blueprint_to_send, 
        "parsing_metadata": {}
    }

    try:
        async def mock_call_ollama_fallback(raw_query):
            from main import Blueprint 
            return Blueprint(**blueprint_to_send)
            
        with patch('main.call_ollama_fallback', new=mock_call_ollama_fallback):
            print(f"DEBUG: About to post payload: {payload}")
            response = await client.post(API_URL, json=payload, timeout=60.0)
            print(f"DEBUG: Response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()

            print(f"DEBUG: Full API Response Data: {json.dumps(data, indent=2)}")
            print(f"DEBUG: SQL Query from API: {data.get('sql_query', 'N/A')}")
            
            if data.get("status") != "success" or not data.get("results"):
                print(f"[FAIL] API returned an error or no results. Message: {data.get('message', 'N/A')}")
                return False

            result_value = data["results"][0].get(test_case["response_key"])
            if result_value is None:
                print(f"[FAIL] Key '{test_case['response_key']}' not found in API response. Actual keys: {list(data['results'][0].keys()) if data['results'] else 'No results'}")
                return False

            expected_value = ground_truth[test_case["truth_key"]]
            
            if abs(result_value - expected_value) < 1e-9:
                print(f"[PASS] Expected {expected_value}, Got {result_value}")
                return True
            else:
                print(f"[FAIL] Expected {expected_value}, Got {result_value}")
                return False

    except httpx.HTTPStatusError as e:
        print(f"[FAIL] HTTP Error! Status: {e.response.status_code}, Body: {e.response.text}")
        return False
    except Exception as e:
        print(f"[FAIL] An unexpected error occurred: {e}")
        return False

async def main():
    try:
        with open(GROUND_TRUTH_FILE, 'r') as f:
            ground_truth = json.load(f)
    except FileNotFoundError:
        print(f"[FAIL] Critical Error: Ground truth file '{GROUND_TRUTH_FILE}' not found.")
        return

    print("\n--- Starting API Accuracy Test Harness ---")
    
    passed_count = 0
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(run_single_test(client, tc, ground_truth) for tc in TEST_CASES))
        passed_count = sum(1 for res in results if res)

    print("\n--- Test Summary ---")
    print(f"Total Tests: {len(TEST_CASES)}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {len(TEST_CASES) - passed_count}")
    print("------------------------")

    if passed_count == len(TEST_CASES):
        print("PASS: All accuracy tests passed successfully!")
    else:
        print("FAIL: One or more accuracy tests failed. Please review the logs.")

if __name__ == "__main__":
    asyncio.run(main())
