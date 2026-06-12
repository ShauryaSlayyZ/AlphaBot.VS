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
    print(f"  SQL: {res.get('sql_query')}")
    print(f"  Results Count: {len(res.get('results', []))}")
    if res.get('results'):
        print(f"  First 3 Results:")
        for r in res.get('results', [])[:3]:
            print(f"    {r}")
    else:
        print("  Results: None")
    print("-" * 60)

async def main():
    MetadataRegistry.get_instance()
    await test_query("compare expenses trend in 2023 and 2024")
    await test_query("compare revenue trend for sales and marketing")
    await test_query("compare headcount in 2024 between north and south regions")

if __name__ == "__main__":
    asyncio.run(main())
