import requests
import json
import time

print("="*80)
print("Testing: 'show me sales team performance'")
print("="*80)

url = "http://localhost:8000/api/query"
query = "show me sales team performance"

payload = {
    "raw_query": query,
    "blueprint": None
}

print(f"\n📤 Sending query: '{query}'")
print("⏳ Waiting for response...")

start = time.time()
try:
    response = requests.post(url, json=payload, timeout=30)
    elapsed = time.time() - start
    
    print(f"\n✅ Response received in {elapsed:.2f} seconds")
    print(f"📊 Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n📋 Response Data:")
        print(f"   Status: {data.get('status')}")
        print(f"   Plants Queried: {data.get('plants_queried')}")
        print(f"   Unit: {data.get('unit')}")
        print(f"   Results Count: {len(data.get('results', []))}")
        
        print(f"\n📈 SQL Query:")
        print(f"   {data.get('sql_query', 'N/A')}")
        
        print(f"\n💰 First Result:")
        if data.get('results'):
            first = data['results'][0]
            for key, value in first.items():
                if isinstance(value, (int, float)):
                    print(f"   {key}: {value:,.2f}")
                else:
                    print(f"   {key}: {value}")
                    
        print(f"\n🎯 Expected behavior:")
        print(f"   - Should filter by department='sales'")
        print(f"   - Should return sales department metrics")
        print(f"   - Should show revenue/profit/expenses for sales")
        
    else:
        print(f"\n❌ Error Response:")
        print(response.text[:500])
        
except requests.exceptions.Timeout:
    print(f"\n❌ Request timed out after 30 seconds")
    print(f"   This means Ollama is taking too long to parse the query")
    
except Exception as e:
    print(f"\n❌ Error: {e}")

print("\n" + "="*80)
