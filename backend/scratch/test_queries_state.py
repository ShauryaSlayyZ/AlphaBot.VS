import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from main import handle_query, QueryBlueprintPayload, MetadataRegistry

# Set up logging to stdout to see tracing
logging.basicConfig(level=logging.INFO)

async def test_state_query():
    # Initialize registry
    registry = MetadataRegistry.get_instance()
    
    q = "Budget Allocated by State"
    payload = QueryBlueprintPayload(raw_query=q)
    try:
        res = await handle_query(payload)
        print("\n=== QUERY RESULT ===")
        print(f"QUERY: '{q}'")
        print(f"STATUS: {res.get('status')}")
        print(f"MESSAGE: {res.get('message')}")
        print(f"SQL: {res.get('sql_query')}")
        print(f"RESULTS: {res.get('results')}")
        print(f"KPIS: {res.get('kpis')}")
    except Exception as e:
        print(f"\nERROR RUNNING QUERY: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_state_query())
