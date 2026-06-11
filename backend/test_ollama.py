import requests
import json

print("=" * 80)
print("TESTING OLLAMA INTEGRATION")
print("=" * 80)

# Test 1: Check if Ollama is running
print("\n1. Testing Ollama connection...")
try:
    response = requests.get("http://localhost:11434/api/tags", timeout=5)
    if response.status_code == 200:
        print("✅ Ollama is running!")
        models = response.json().get('models', [])
        print(f"✅ Available models: {[m['name'] for m in models]}")
    else:
        print(f"❌ Ollama responded with status {response.status_code}")
except Exception as e:
    print(f"❌ Cannot connect to Ollama: {e}")
    exit(1)

# Test 2: Test query parsing
print("\n2. Testing natural language query parsing...")
test_query = "how much money did we make last year in sales?"

payload = {
    "model": "phi3.5:3.8b",
    "prompt": json.dumps({
        "query": test_query,
        "response_format": {
            "metrics": ["string"],
            "filters": [{"column": "string", "value": "string"}],
            "timeframe": {"type": "string", "value": "string"}
        }
    }),
    "system": "Return ONLY JSON. Valid Metrics: ['revenue', 'profit', 'expenses', 'headcount', 'salary', 'tax_liability', 'asset_value', 'operating_cost', 'marketing_spend', 'customer_count'].",
    "stream": False,
    "format": "json"
}

try:
    print(f"   Query: '{test_query}'")
    response = requests.post(
        "http://localhost:11434/api/generate",
        json=payload,
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        parsed = json.loads(result['response'])
        print("✅ Ollama parsed the query!")
        print(f"   Metrics: {parsed.get('metrics', [])}")
        print(f"   Filters: {parsed.get('filters', [])}")
        print(f"   Timeframe: {parsed.get('timeframe', {})}")
    else:
        print(f"❌ Ollama error: {response.status_code}")
        print(response.text[:200])
        
except Exception as e:
    print(f"❌ Parsing error: {e}")

# Test 3: Test Alphabot API with natural language
print("\n3. Testing Alphabot API with natural language query...")
try:
    api_response = requests.post(
        "http://localhost:8000/api/query",
        json={"raw_query": "how much revenue did we make in 2026?", "blueprint": None},
        timeout=15
    )
    
    if api_response.status_code == 200:
        data = api_response.json()
        print("✅ Alphabot API responded!")
        print(f"   Status: {data.get('status')}")
        print(f"   Plants queried: {data.get('plants_queried')}")
        print(f"   Results: {len(data.get('results', []))} row(s)")
        if data.get('results'):
            first = data['results'][0]
            for k, v in first.items():
                if isinstance(v, (int, float)):
                    print(f"   {k}: {v:,.2f}")
    else:
        print(f"❌ API error: {api_response.status_code}")
        
except Exception as e:
    print(f"❌ API test error: {e}")

print("\n" + "=" * 80)
print("OLLAMA SETUP COMPLETE!")
print("=" * 80)
print("\nYou can now use natural language queries like:")
print("  • 'how much money did we make last year?'")
print("  • 'show me sales performance'")
print("  • 'which department earned the most?'")
print("  • 'compare profits across all plants'")
print("\nOllama will automatically parse these into structured queries!")
