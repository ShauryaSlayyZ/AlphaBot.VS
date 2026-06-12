import sys
import os
import asyncio
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import handle_query, QueryBlueprintPayload, MetadataRegistry, RESULT_CACHE

async def main():
    MetadataRegistry.get_instance()
    
    # Define queries
    q1 = "revenue in sales in 2026"
    q2 = "revenue in sales in 2026"                   # Exact match (Result cache hit)
    q3 = "what is the sales revenue in year 2026"     # Semantic match (Semantic cache hit, DB query run)
    q4 = "what is the sales revenue in year 2026"     # Second semantic match (Result cache hit)
    
    print("=" * 80)
    print("BENCHMARKING SEMANTIC & RESULT CACHING LAYERS")
    print("=" * 80)
    
    # 1. First Run (Ollama + DB)
    print(f"\n1. Query: '{q1}' (First run - Cold)")
    start = time.perf_counter()
    res1 = await handle_query(QueryBlueprintPayload(raw_query=q1))
    t1 = (time.perf_counter() - start) * 1000
    meta1 = res1.get("metadata", {})
    print(f"   Total elapsed: {t1:.2f} ms")
    print(f"   Backend time:  {meta1.get('backend_ms'):.2f} ms")
    print(f"   Cache hit:     {meta1.get('cache_hit')}")
    print(f"   Semantic hit:  {meta1.get('used_semantic_cache')}")
    
    # 2. Second Run (Result Cache Hit)
    print(f"\n2. Query: '{q2}' (Second run - Exact Match)")
    start = time.perf_counter()
    res2 = await handle_query(QueryBlueprintPayload(raw_query=q2))
    t2 = (time.perf_counter() - start) * 1000
    meta2 = res2.get("metadata", {})
    print(f"   Total elapsed: {t2:.2f} ms")
    print(f"   Backend time:  {meta2.get('backend_ms'):.2f} ms")
    print(f"   Cache hit:     {meta2.get('cache_hit')} (Type: {meta2.get('cache_type')})")
    print(f"   Semantic hit:  {meta2.get('used_semantic_cache')}")
    assert meta2.get("cache_hit") is True
    
    # Clear result cache to test semantic cache hit with result cache miss
    print("\n--- Clearing Result Cache ---")
    RESULT_CACHE.clear()
    
    # 3. Third Run (Semantic Cache Hit, DB Run)
    print(f"\n3. Query: '{q3}' (Third run - Semantic Match)")
    start = time.perf_counter()
    res3 = await handle_query(QueryBlueprintPayload(raw_query=q3))
    t3 = (time.perf_counter() - start) * 1000
    meta3 = res3.get("metadata", {})
    print(f"   Total elapsed: {t3:.2f} ms")
    print(f"   Backend time:  {meta3.get('backend_ms'):.2f} ms")
    print(f"   Cache hit:     {meta3.get('cache_hit')}")
    print(f"   Semantic hit:  {meta3.get('used_semantic_cache')}")
    assert meta3.get("cache_hit") is False
    assert meta3.get("used_semantic_cache") is True
    
    # 4. Fourth Run (Result Cache Hit on Semantic query)
    print(f"\n4. Query: '{q4}' (Fourth run - Semantic Result Match)")
    start = time.perf_counter()
    res4 = await handle_query(QueryBlueprintPayload(raw_query=q4))
    t4 = (time.perf_counter() - start) * 1000
    meta4 = res4.get("metadata", {})
    print(f"   Total elapsed: {t4:.2f} ms")
    print(f"   Backend time:  {meta4.get('backend_ms'):.2f} ms")
    print(f"   Cache hit:     {meta4.get('cache_hit')} (Type: {meta4.get('cache_type')})")
    print(f"   Semantic hit:  {meta4.get('used_semantic_cache')}")
    assert meta4.get("cache_hit") is True
    assert meta4.get("used_semantic_cache") is True
    
    print("\n" + "=" * 80)
    print("✅ ALL CACHING TESTS PASSED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
