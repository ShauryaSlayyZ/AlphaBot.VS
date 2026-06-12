import sys
import os
import asyncio
import httpx
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import MetadataRegistry, OLLAMA_URL, OLLAMA_MODEL

async def main():
    registry = MetadataRegistry.get_instance()
    system_prompt = f"""You are a query parser for a business analytics system. Parse the user's natural language query into structured JSON.

Valid Metrics: {list(registry.metrics.keys())}
Valid Departments: sales, digital, marketing, hr, engineering, finance, support, operations
Valid Regions: north, south, east, west, central
Valid Operations: SUM, AVERAGE, BREAKDOWN, GRAPH

Important parsing rules:
- "sales" or "sales team" or "sales department" → filter: {{"column": "department", "value": "sales"}}
- "digital" or "digital team" → filter: {{"column": "department", "value": "digital"}}
- "performance" usually means show metrics (revenue, profit)
- "money" or "earnings" → metric: revenue
- "employees" or "people" → metric: headcount
- "expenses" or "spend" or "spending" or "cost" → metric: expenses (unless it is "operating cost" or "marketing spend")
- "operating cost" or "op cost" → metric: operating_cost
- "marketing spend" or "marketing cost" → metric: marketing_spend
- "salary" or "salaries" or "payroll" → metric: salary
- "tax" or "taxes" or "tax liability" → metric: tax_liability
- "asset value" or "assets" → metric: asset_value
- "customer count" or "customers" or "clients" → metric: customer_count
- "profit" or "earnings" or "margin" → metric: profit (unless "revenue" is requested)
- "trend", "over time", or "by year" → operation: GRAPH
- "breakdown" or "compare" or "by" → operation: BREAKDOWN (unless it is "by year", then use GRAPH)
- Years like "2026" → timeframe: {{"type": "year", "value": "2026"}}

Return ONLY valid JSON in this exact format:
{{
  "metrics": ["revenue"],
  "filters": [{{"column": "department", "value": "sales"}}],
  "timeframe": {{"type": "year", "value": "2026"}},
  "operation": "SUM"
}}"""

    queries = [
        "compare expenses trend in 2023 and 2024",
        "compare revenue between sales and marketing",
        "compare headcount in 2024 between north and south regions"
    ]

    async with httpx.AsyncClient(timeout=40.0) as client:
        for q in queries:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL, 
                "prompt": f"Parse this query: {q}", 
                "system": system_prompt, 
                "stream": False, 
                "format": "json"
            })
            print(f"QUERY: {q}")
            print(resp.json()['response'])
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
