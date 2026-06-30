import requests, json, time

time.sleep(8)

queries = [
    "Compare Budget Allocated in Gujarat and Rajasthan for 2025",
    "Compare budget in Gujarat and Maharashtra",
    "Show revenue in Gujarat and Rajasthan",
    "Budget allocated in Gujarat vs Rajasthan 2025",
]

for q in queries:
    try:
        r = requests.post('http://localhost:8000/api/query', json={'raw_query': q}, timeout=25)
        d = r.json()
        status = d.get('status', 'unknown')
        results = d.get('results', [])
        sql = d.get('sql_query', 'N/A')
        msg = d.get('message', '')
        print(f"Query: {repr(q)}")
        print(f"  Status: {status}, Results: {len(results)}")
        print(f"  SQL: {sql[:300]}")
        if msg:
            print(f"  Message: {msg[:150]}")
        if results:
            print(f"  Keys: {list(results[0].keys())}")
            for row in results[:4]:
                print(f"    {row}")
        print()
    except Exception as e:
        print(f"Query: {repr(q)} -> ERROR: {e}\n")
