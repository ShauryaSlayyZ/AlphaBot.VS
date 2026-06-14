import os
import sys
import asyncio
import time

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

async def main():
    from main import handle_query, QueryBlueprintPayload
    
    q = "revenue trend across all plants from 2022 to 2025"
    payload = QueryBlueprintPayload(raw_query=q, blueprint=None, force_llm=False)
    
    print(f"Executing query: '{q}'...")
    start_time = time.perf_counter()
    try:
        res = await handle_query(payload)
        elapsed = time.perf_counter() - start_time
        print(f"\nQuery completed in {elapsed:.4f}s.")
        print(f"Status: {res.get('status')}")
        print(f"Results Count: {len(res.get('results', []))}")
        print(f"KPIs: {res.get('kpis')}")
        print(f"SQL: {res.get('sql_query')}")
    except Exception as e:
        import traceback
        print(f"Error occurred: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
