import sys
import os
import json
import httpx
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import OLLAMA_URL, OLLAMA_MODEL, MetadataRegistry, POWER_PLANTS

async def test():
    registry = MetadataRegistry.get_instance()
    system_prompt = (
        "You are a high-precision SQL query assistant for AGEL project tracking. "
        "Strictly map query to JSON blueprint. "
        f"Metrics: {list(registry.metrics.keys())}. "
        f"Sites: {POWER_PLANTS}. "
        "Map 'grand blue'/'grand' to 'grand_gulf'. Map 'digital' to project_type filter 'digital'."
    )
    raw_query = "what is the breakdown graph of palo_verde in year 2026"
    print("Prompting Ollama model...")
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": raw_query,
                "system": system_prompt,
                "stream": False,
                "format": "json"
            }
        )
        print("Raw response:")
        print(resp.json())

asyncio.run(test())
