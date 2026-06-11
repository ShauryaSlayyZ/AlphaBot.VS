import requests
import json
import time

API_URL = "http://localhost:8000/api/query"

test_queries = [
    "total revenue in 2026",
    "profit breakdown by plant for 2026",
    "revenue in sales department for 2026",
    "show all metrics for digital in north for 2026",
]

print("=" * 80)
print("LIVE API TEST - Running Sample Queries")
print("=" * 80)

for i, query in enumerate(test_queries, 1):
    print(f"\n{i}. Query: '{query}'")
    print("-" * 80)
    
    start = time.time()
    try:
        response = requests.post(
            API_URL,
            json={"raw_query": query, "blueprint": None},
            timeout=10
        )
        elapsed = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Status: SUCCESS")
            print(f"⏱️  Time: {elapsed:.0f}ms (Backend: {data.get('metadata', {}).get('backend_ms', 0):.0f}ms)")
            print(f"🏭 Plants Queried: {data.get('plants_queried', 0)}")
            print(f"📊 Results: {len(data.get('results', []))} row(s)")
            print(f"💵 Unit: {data.get('unit', 'N/A')}")
            
            # Show first result
            if data.get('results'):
                first_result = data['results'][0]
                print(f"📈 First Result:")
                for key, value in first_result.items():
                    if isinstance(value, (int, float)):
                        print(f"   • {key}: {value:,.2f}")
                    else:
                        print(f"   • {key}: {value}")
            
            print(f"🔍 SQL: {data.get('sql_query', 'N/A')[:100]}...")
        else:
            print(f"❌ Error: HTTP {response.status_code}")
            print(response.text[:200])
            
    except requests.exceptions.ConnectionError:
        print("❌ Error: Cannot connect to backend. Is it running on port 8000?")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

print("\n" + "=" * 80)
print("Test Complete!")
print("=" * 80)
