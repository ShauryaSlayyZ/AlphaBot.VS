import sys
import os
sys.path.append(os.path.abspath('.'))

from backend.main import parse_query_deterministically

q1 = "Compare tax liability in sales department at diablo canyon from 2021 to 2025"
q2 = "marketing spend breakdown by department at palo verde from 2022 through 2026"
q3 = "Compare marketing spend and asset value in marketing department at Grand Gulf in 2025"
q4 = "top plants by profit in sales department from 2023 to 2026"

print("=== PARSER RESULTS ===")
for i, q in enumerate([q1, q2, q3, q4], 1):
    res = parse_query_deterministically(q)
    print(f"\nQ{i}: {q}")
    if res is None:
        print("RESULT: None (Fallback to LLM)")
    elif res.get("error"):
        print(f"ERROR: {res['error']}")
    else:
        bp = res["blueprint"]
        print(f"INTENT: {res['intent']}")
        print(f"METRICS: {bp.metrics}")
        print(f"OPERATION: {bp.operation}")
        print(f"FILTERS: {bp.filters}")
        print(f"COMPARISON: {bp.comparison}")
        print(f"TIMEFRAME: {bp.timeframe}")
        print(f"LIMIT/ORDER: {bp.limit} / {bp.sort_asc}")
