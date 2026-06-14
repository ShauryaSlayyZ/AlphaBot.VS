import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app, MetadataRegistry, SemanticSchemaAdapter

def test():
    # Force registry init using real databases
    registry = MetadataRegistry.get_instance()
    SemanticSchemaAdapter.get_instance().build_schema_maps(registry)
    
    client = TestClient(app)
    
    queries = [
        "Budget Allocated by State",
        "Completion Percentage by Project Type",
        "Delay Days by Contractor"
    ]
    
    for q in queries:
        print(f"\n==================================================")
        print(f"QUERY: '{q}'")
        resp = client.post("/api/query", json={"raw_query": q})
        print(f"STATUS CODE: {resp.status_code}")
        print("RESPONSE:")
        try:
            import json
            print(json.dumps(resp.json(), indent=2))
        except Exception as e:
            print(resp.text)

if __name__ == "__main__":
    test()
