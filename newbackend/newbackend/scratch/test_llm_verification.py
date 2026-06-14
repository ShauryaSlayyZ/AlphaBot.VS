import json
import re

class MockRegistry:
    metrics = {
        "capacity_mw": {},
        "budget_allocated": {},
        "budget_used": {},
        "revenue": {}
    }
    categoricals = {
        "project_type": {"values": ["Solar", "Wind", "Hybrid"]},
        "location": {"values": ["Gujarat", "Rajasthan"]}
    }

POWER_PLANTS = ['darlington', 'diablo_canyon', 'grand_gulf', 'hinkley_point', 'kashiwazaki', 'palo_verde', 'three_mile_island', 'vogtle']

def parse_llm_response(resp_text: str, raw_query: str) -> dict:
    resp_text = resp_text.strip()
    
    # Extract only the JSON block
    match = re.search(r'\{.*\}', resp_text, re.DOTALL)
    if match:
        resp_text = match.group(0)
        
    # Perform cleanups
    resp_text = re.sub(r',\s*null\s*', '', resp_text)
    resp_text = re.sub(r'null\s*,?\s*\]', ']', resp_text)
    resp_text = re.sub(r',\s*\]', ']', resp_text)
    resp_text = re.sub(r',\s*\}', '}', resp_text)
    
    data = None
    try:
        data = json.loads(resp_text)
    except Exception as e:
        print(f"Failed to parse cleaned JSON: {e}")
        data = {}
        
    # Flatten nested dictionaries
    for nest_key in ["query", "blueprint", "response"]:
        if nest_key in data and isinstance(data[nest_key], dict):
            data.update(data[nest_key])
            
    # Reconstruct standard fields
    bp_data = {
        "operation": "SUM",
        "metrics": [],
        "filters": [],
        "timeframe": None,
        "timeframes": [],
        "is_range": False,
        "comparison": None,
        "breakdown_by": None
    }
    
    # Map operation
    op = data.get("operation") or data.get("op") or data.get("type")
    if op and isinstance(op, str):
        bp_data["operation"] = op.upper()
    else:
        for possible_op in ["BREAKDOWN", "GRAPH", "TREND", "COMPARE", "SUM", "AVERAGE", "MIN", "MAX"]:
            if possible_op.lower() in raw_query.lower() or possible_op.lower() in resp_text.lower():
                bp_data["operation"] = possible_op
                break
                
    # Map metrics
    metrics_list = data.get("metrics") or data.get("metric")
    if isinstance(metrics_list, str):
        metrics_list = [metrics_list]
    if isinstance(metrics_list, list):
        for m in metrics_list:
            if m and isinstance(m, str) and m in MockRegistry.metrics:
                bp_data["metrics"].append(m)
                
    if not bp_data["metrics"]:
        for m in MockRegistry.metrics:
            if m.lower() in raw_query.lower():
                bp_data["metrics"].append(m)
        if not bp_data["metrics"]:
            bp_data["metrics"] = ["revenue"]

    # Map filters / categoricals
    filters_list = data.get("filters")
    if isinstance(filters_list, list):
        for f in filters_list:
            if isinstance(f, dict) and "column" in f and "value" in f:
                bp_data["filters"].append(f)
                
    for plant_key in ["site", "plant", "location"]:
        plant_val = data.get(plant_key)
        if plant_val and isinstance(plant_val, str):
            for p in POWER_PLANTS:
                if p.lower() in plant_val.lower() or plant_val.lower() in p.lower():
                    if not any(f["column"] == "plant" and f["value"] == p for f in bp_data["filters"]):
                        bp_data["filters"].append({"column": "plant", "value": p})
                    break

    # Extract timeframe / year
    year_val = data.get("year") or data.get("fy_year") or data.get("timeframe")
    if year_val:
        year_str = str(year_val).replace("FY", "").strip()
        if year_str.isdigit():
            bp_data["timeframe"] = {"type": "year", "value": year_str}
            bp_data["timeframes"] = [{"type": "year", "value": year_str}]
    else:
        year_match = re.search(r'\b(20\d{2})\b', raw_query + " " + resp_text)
        if year_match:
            bp_data["timeframe"] = {"type": "year", "value": year_match.group(1)}
            bp_data["timeframes"] = [{"type": "year", "value": year_match.group(1)}]

    # Map other dimensions
    for col_name, cat in MockRegistry.categoricals.items():
        val = data.get(col_name)
        if val and isinstance(val, str):
            for allowed in cat["values"]:
                if val.lower() == allowed.lower():
                    bp_data["filters"].append({"column": col_name, "value": allowed})
                    break

    return bp_data

if __name__ == "__main__":
    raw_response = """{\n  "query": {\n    "site": "palo_verde",\n    "year": 2026,\n    "metrics": [\n      "capacity_mw",\n      "budget_allocated",\n      "budget_used",\nnull      \n     ]\n   }\n}"""
    raw_query = "what is the breakdown graph of palo_verde in year 2026"
    print("Parsing raw response...")
    result = parse_llm_response(raw_response, raw_query)
    print("Parsed Blueprint Data:")
    print(json.dumps(result, indent=2))
