import requests, json

def test_query_verbose(q):
    try:
        r = requests.post('http://localhost:8000/api/query', json={'raw_query': q}, timeout=30)
        data = r.json()
        status = data.get('status', 'unknown')
        results = data.get('results', [])
        msg = data.get('message', '')
        sql = data.get('sql_query', '')
        print(f"Query: {repr(q)}")
        print(f"  Status: {status}, Results: {len(results)}")
        print(f"  SQL: {sql[:200] if sql else 'N/A'}")
        if msg:
            print(f"  Msg: {msg[:100]}")
        if results:
            print(f"  Keys: {list(results[0].keys())}")
            if len(results) <= 20:
                for r in results:
                    print(f"    {r}")
            else:
                print(f"  First: {results[0]}")
                print(f"  Last:  {results[-1]}")
        print()
    except Exception as e:
        print(f"Query: {repr(q)} -> ERROR: {e}")
        print()

test_query_verbose("compare revenue across project type")
