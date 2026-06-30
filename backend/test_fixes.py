import requests, json, sys

def test_query(q):
    try:
        r = requests.post('http://localhost:8000/api/query', json={'raw_query': q}, timeout=20)
        data = r.json()
        status = data.get('status', 'unknown')
        results = data.get('results', [])
        msg = data.get('message', '')
        print(f"Query: {repr(q)}")
        print(f"  Status: {status}, Results: {len(results)}")
        if msg:
            print(f"  Msg: {msg[:100]}")
        if results:
            print(f"  Keys: {list(results[0].keys())[:6]}")
        print()
    except Exception as e:
        print(f"Query: {repr(q)} -> ERROR: {e}")
        print()

test_query("compare revnue across prject type")
test_query("compare revenue across project type")
test_query("show budget in Maharashtra")
test_query("budget allocated in Tamil Nadu")
test_query("revenue in Telangana")
test_query("compare revenue across states")
