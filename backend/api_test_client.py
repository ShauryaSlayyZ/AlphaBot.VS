
import httpx
import json

# This script simulates the frontend calling the backend API.

API_URL = "http://localhost:8000/api/query"

# This is the blueprint that the frontend would generate for the failing query.
# We send it directly to test the backend in isolation.
payload = {
  "raw_query": "what is total revenue of digital department in year 2025",
  "blueprint": {
    "operation": "WHAT",
    "metrics": [
      "revenue"
    ],
    "filters": [
      {
        "column": "department",
        "value": "digital department"
      }
    ],
    "timeframe": {
      "type": "year",
      "value": "2025"
    }
  }
}

def run_test():
    print(f"▶️  Sending POST request to {API_URL}...")
    print("PAYLOAD:")
    print(json.dumps(payload, indent=2))
    
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(API_URL, json=payload)
            
            print(f"\n◀️  Received response (Status: {response.status_code})")
            print("RESPONSE BODY:")
            
            # Pretty-print the JSON response
            try:
                response_json = response.json()
                print(json.dumps(response_json, indent=2))
            except json.JSONDecodeError:
                print("Error: Could not decode JSON response.")
                print(response.text)

    except httpx.RequestError as e:
        print(f"\n❌ Request failed: {e}")
        print("Please ensure the backend server is running on http://localhost:8000")

if __name__ == "__main__":
    run_test()
