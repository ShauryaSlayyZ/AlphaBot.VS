import requests
import json

print("Testing Alphabot API...")

# Test 1: Simple query
print("\n1. Testing: 'total revenue in 2026'")
try:
    response = requests.post(
        "http://localhost:8000/api/query",
        json={"raw_query": "total revenue in 2026", "blueprint": None},
        timeout=10
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Success!")
        print(f"Results: {data.get('results', [])[:1]}")
    else:
        print(f"❌ Error: {response.text}")
except Exception as e:
    print(f"❌ Exception: {e}")

print("\n" + "="*60)
print("If you see results above, the API is working!")
print("Open http://localhost:3000 in your browser to use the UI")
print("="*60)
