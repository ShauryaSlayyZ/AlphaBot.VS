import requests, time, json

time.sleep(5)

# Test 1: Create session
r = requests.post('http://localhost:8000/api/session')
data = r.json()
sid = data['session_id']
print(f"Session created: {sid[:8]}...")

# Test 2: First query - should set conversation state
r = requests.post('http://localhost:8000/api/query', json={
    'raw_query': 'Show budget allocated in Gujarat for 2025',
    'session_id': sid
}, timeout=20)
d = r.json()
status = d.get('status')
print(f"Query 1 status: {status}")
ctx = d.get('conversation_context')
if ctx:
    print(f"  metric={ctx.get('active_metric')}")
    print(f"  filters={ctx.get('active_filters')}")
    print(f"  timeframe={ctx.get('active_timeframe')}")
    print(f"  entities={ctx.get('comparison_entities')}")
else:
    print("  No conversation_context!")

# Test 3: Follow-up query - "What about Rajasthan?"
print("\nTest 3: Follow-up 'What about Rajasthan?'")
r = requests.post('http://localhost:8000/api/query', json={
    'raw_query': 'What about Rajasthan?',
    'session_id': sid
}, timeout=20)
d2 = r.json()
print(f"Query 2 status: {d2.get('status')}")
ctx2 = d2.get('conversation_context')
if ctx2:
    print(f"  metric={ctx2.get('active_metric')}")
    print(f"  filters={ctx2.get('active_filters')}")
    print(f"  entities={ctx2.get('comparison_entities')}")
    print(f"  was_rewritten={ctx2.get('was_rewritten')}")

# Test 4: GET session - simulate page refresh rehydration
print("\nTest 4: GET /api/session (rehydration)")
r = requests.get(f'http://localhost:8000/api/session/{sid}')
state = r.json()
print(f"  has_context={state.get('has_context')}")
print(f"  metric={state.get('active_metric')}")
print(f"  entities={state.get('comparison_entities')}")
print(f"  last_query={state.get('last_query')}")

# Test 5: "Compare both" after refresh
print("\nTest 5: 'Compare both' (after simulated refresh)")
r = requests.post('http://localhost:8000/api/query', json={
    'raw_query': 'Compare both',
    'session_id': sid
}, timeout=20)
d3 = r.json()
print(f"Query 3 status: {d3.get('status')}")
ctx3 = d3.get('conversation_context')
print(f"  was_rewritten={ctx3.get('was_rewritten') if ctx3 else 'N/A'}")
if d3.get('results'):
    print(f"  results count: {len(d3['results'])}")
    print(f"  first result: {d3['results'][0] if d3['results'] else 'empty'}")
