import sys
import os
import asyncio
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import handle_query, QueryBlueprintPayload, MetadataRegistry

async def test_query(q):
    payload = QueryBlueprintPayload(raw_query=q, blueprint=None)
    res = await handle_query(payload)
    print(f"QUERY: '{q}'")
    print(f"  Blueprint: operation={res.get('sql_query')}")
    print(f"  Results Count: {len(res.get('results', []))}")
    if res.get('results'):
        print(f"  First Result: {res.get('results')[0]}")
    else:
        print("  Results: None")
    print("-" * 60)

async def main():
    MetadataRegistry.get_instance()
    await test_query("expenses trend in 2025")
    await test_query("expenses trend in 2023")

if __name__ == "__main__":
    asyncio.run(main())
