
import time
import sqlite3
import json
import httpx
import logging
import asyncio
import os
import re
import glob
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

# --- Dynamic Federated Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def discover_power_plants():
    """Scans the directory for .db files and treats them as data sources."""
    ignore_list = ['benchmark_test.db', 'market_intel.db', 'corporate_metrics_db_7.db', 'corporate_metrics_db_8.db']
    db_files = glob.glob(os.path.join(BASE_DIR, "*.db"))
    plants = []
    for f in db_files:
        name = os.path.basename(f)
        if name not in ignore_list:
            plants.append(os.path.splitext(name)[0])
    return sorted(plants)

POWER_PLANTS = discover_power_plants()
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3.5:3.8b"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alphabot-federated-engine")

# --- Metadata Registry (Singleton / Auto-Discovery) ---
class MetadataRegistry:
    _instance = None
    _last_checked = 0.0
    _db_mtimes = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance._initialized = False
            cls._instance.metrics = {}
            cls._instance.categoricals = {}
            cls._instance.initialize()
            cls._db_mtimes = {}
            for db in discover_power_plants():
                path = os.path.join(BASE_DIR, f"{db}.db")
                if os.path.exists(path):
                    cls._db_mtimes[db] = os.path.getmtime(path)
        else:
            now = time.time()
            if now - cls._last_checked > 5.0:
                cls._last_checked = now
                current_dbs = discover_power_plants()
                needs_reload = False
                
                global POWER_PLANTS
                if set(current_dbs) != set(POWER_PLANTS):
                    needs_reload = True
                else:
                    for db in current_dbs:
                        path = os.path.join(BASE_DIR, f"{db}.db")
                        if os.path.exists(path):
                            mtime = os.path.getmtime(path)
                            if cls._db_mtimes.get(db) != mtime:
                                needs_reload = True
                                break
                if needs_reload:
                    logger.info("🔄 Schema drift or DB file modification detected! Hot-reloading registry...")
                    cls._instance._initialized = False
                    cls._instance.initialize()
                    cls._db_mtimes.clear()
                    for db in current_dbs:
                        path = os.path.join(BASE_DIR, f"{db}.db")
                        if os.path.exists(path):
                            cls._db_mtimes[db] = os.path.getmtime(path)
        return cls._instance

    def initialize(self):
        if self._initialized: return
        start_init = time.perf_counter()
        
        global POWER_PLANTS
        POWER_PLANTS = discover_power_plants()
        logger.info(f"🚀 Found {len(POWER_PLANTS)} dynamic data sources: {POWER_PLANTS}")
        
        self.metrics.clear()
        self.categoricals.clear()

        if not POWER_PLANTS:
            logger.error("FATAL: No database files found.")
            return

        for plant in POWER_PLANTS:
            db_path = os.path.join(BASE_DIR, f"{plant}.db")
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
                res = cursor.fetchone()
                if not res: continue
                table_name = res[0]
                
                cursor.execute(f"PRAGMA table_info({table_name})")
                cols = {c[1]: c[2].upper() for c in cursor.fetchall()}
                
                # 1. Metric Discovery
                for col_name, col_type in cols.items():
                    if any(m in col_name.lower() for m in ['revenue', 'profit', 'expenses', 'headcount', 'salary', 'tax', 'asset', 'cost', 'capacity', 'completion', 'delay', 'budget']):
                        self.metrics[col_name] = {"column": col_name, "type": col_type}
                    
                    # 2. Dimension Value Sampling
                    # 2. Dimension Value Sampling
                    if col_name in ['project_type', 'location', 'state', 'contractor_name', 'department', 'category', 'project_name', 'project_id', 'contractor_payment_status', 'material_status']:
                        if col_name not in self.categoricals: 
                            self.categoricals[col_name] = {"values": set()}
                        # Limit sampling to avoid memory issues, prioritize IDs
                        limit = 100 if col_name == 'project_id' else 50
                        cursor.execute(f"SELECT DISTINCT {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL LIMIT {limit}")
                        self.categoricals[col_name]["values"].update([row[0] for row in cursor.fetchall()])
                    elif col_name == 'fy_year':
                        if 'fy_year' not in self.categoricals:
                            self.categoricals['fy_year'] = {"values": set()}
                        cursor.execute(f"SELECT DISTINCT fy_year FROM {table_name} WHERE fy_year IS NOT NULL")
                        self.categoricals['fy_year']["values"].update([int(row[0]) for row in cursor.fetchall() if str(row[0]).isdigit()])

                conn.close()
            except Exception as e:
                logger.error(f"Discovery Error on {plant}: {e}")

        for k in self.categoricals:
            self.categoricals[k]["values"] = list(self.categoricals[k]["values"])

        self._initialized = True
        init_ms = (time.perf_counter() - start_init) * 1000
        logger.info(f"✅ Schema Discovery Complete in {init_ms:.2f}ms. Metrics: {list(self.metrics.keys())}")

# --- Pydantic Models ---
class Blueprint(BaseModel):
    operation: Optional[str] = "SUM"
    metrics: List[str] = []
    filters: List[Dict[str, str]] = []
    timeframe: Optional[Dict[str, str]] = None
    timeframes: List[Dict[str, str]] = [] 
    is_range: bool = False
    comparison: Optional[Dict[str, Any]] = None
    breakdown_by: Optional[str] = None

class QueryBlueprintPayload(BaseModel):
    raw_query: str
    blueprint: Optional[Blueprint] = None
    force_llm: bool = False
    parsing_metadata: Optional[Dict[str, Any]] = None

# --- Federated Query Engine ---
async def run_query_on_single_db(plant: str, sql: str, params: tuple) -> List[Dict]:
    db_file = os.path.join(BASE_DIR, f"{plant}.db")
    if not os.path.exists(db_file): return []
    
    loop = asyncio.get_event_loop()
    def query():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
            res = cursor.fetchone()
            if not res: return []
            table_name = res[0]
            final_sql = sql.replace("{table_name}", table_name)
            cursor.execute(final_sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Query Error on {plant}: {e}")
            return []
        finally:
            conn.close()
    return await loop.run_in_executor(None, query)

def build_federated_query_parts(bp: Blueprint) -> (str, List[str], tuple, str, str, str):
    registry = MetadataRegistry.get_instance()
    where_clauses, params = [], []
    valid_dims = list(registry.categoricals.keys())
    
    # Group filter values by target database column (Case 1: Dual-Dimension Collision)
    col_to_filters = {}
    for f in bp.filters:
        col, val = f['column'].lower(), f['value']
        target = None
        if col in valid_dims: target = col
        elif col == "department" and "project_type" in valid_dims: target = "project_type"
        elif col == "site" and "location" in valid_dims: target = "location"
        elif col == "plant": continue
        
        if target:
            # Case-normalization in Python to match exact DB casing and leverage index
            allowed_vals = registry.categoricals[target]["values"]
            normalized_val = val
            for av in allowed_vals:
                if str(av).lower() == str(val).lower():
                    normalized_val = av
                    break
            if target not in col_to_filters:
                col_to_filters[target] = []
            col_to_filters[target].append(normalized_val)
        else:
            where_clauses.append("1 = 0") # Block whole-table leak if filter is invalid

    for target, vals in col_to_filters.items():
        if len(vals) == 1:
            where_clauses.append(f"{target} = ?")
            params.append(vals[0])
        else:
            placeholders = ",".join(["?"] * len(vals))
            where_clauses.append(f"{target} IN ({placeholders})")
            params.extend(vals)

    # 2. Numeric Comparisons (e.g., delay < 25)
    if bp.comparison:
        comp = bp.comparison
        c_metric = comp.get('metric')
        c_op = comp.get('operator')
        c_val = comp.get('value')
        if c_metric in registry.metrics and c_op in ['<', '>', '=', '<=', '>=']:
            where_clauses.append(f"{c_metric} {c_op} ?")
            params.append(c_val)

    if bp.timeframe and not bp.timeframes: bp.timeframes = [bp.timeframe]
    if bp.timeframes:
        dates_val = []
        years_val = []
        for tf in bp.timeframes:
            val_str = str(tf.get('value', '')).replace("FY", "")
            if tf.get('type') == 'date' or re.match(r'^\d{4}-\d{2}-\d{2}$', val_str):
                dates_val.append(val_str[:10])
            else:
                if val_str.isdigit():
                    years_val.append(int(val_str))
                else:
                    years_val.append(val_str)
                    
        # Apply date filters (Case 4: Timestamp Date Range Safety)
        for d in dates_val:
            where_clauses.append("record_date BETWEEN ? AND ?")
            params.extend([f"{d} 00:00:00", f"{d} 23:59:59"])
            
        # Apply year filters (Indexed lookup)
        if years_val:
            if len(years_val) == 1:
                where_clauses.append("fy_year = ?")
                params.append(years_val[0])
            else:
                placeholders = ",".join(["?"] * len(years_val))
                where_clauses.append(f"fy_year IN ({placeholders})")
                params.extend(years_val)

    # Detect profile request
    is_profile_request = 'project_id' in col_to_filters and not bp.metrics
    
    # Allow empty metric_cols ONLY IF is_profile_request is true
    metric_cols = [m for m in bp.metrics if m in registry.metrics]
    if not metric_cols and not is_profile_request:
        metric_cols = ["revenue"]

    sql_group_by, sql_order_by, group_col = "", "", None
    
    if is_profile_request:
        sql_select = "*"
    else:
        op = bp.operation.upper() if bp.operation else "SUM"
        if len(bp.timeframes) > 1 or op in ["GRAPH", "TREND"]:
            group_col = "strftime('%Y', record_date) as label" if len(bp.timeframes) > 1 else "strftime('%Y-%m', record_date) as label"
            sql_group_by = f"GROUP BY {group_col.split(' as ')[0]}"
            sql_order_by = "ORDER BY label ASC"
        elif op == "BREAKDOWN":
            # Resolve target breakdown column
            group_col_name = None
            if bp.breakdown_by:
                bby = bp.breakdown_by.lower().strip()
                if bby in valid_dims: group_col_name = bby
                elif bby == "department" and "project_type" in valid_dims: group_col_name = "project_type"
                elif bby == "site" and "location" in valid_dims: group_col_name = "location"
                
            if not group_col_name:
                filtered_cols = [f['column'].lower() for f in bp.filters]
                filtered_db_cols = []
                for c in filtered_cols:
                    if c == "department": filtered_db_cols.append("project_type")
                    elif c in ["plant", "site"]: filtered_db_cols.append("location")
                    else: filtered_db_cols.append(c)
                
                group_candidates = ['project_type', 'location', 'state', 'category', 'contractor_name']
                for cand in group_candidates:
                    if cand in valid_dims and cand not in filtered_db_cols:
                        group_col_name = cand
                        break
                        
            if not group_col_name:
                group_col_name = "project_type" if "project_type" in valid_dims else "location"
                
            group_col = f"{group_col_name} as label"
            sql_group_by = f"GROUP BY {group_col_name}"
            
        select_parts = []
        if group_col:
            select_parts.append(group_col)
        
        for m in metric_cols:
            # Case 3: Rate column average aggregation fallback
            for m in metric_cols:
                # Check if metric is actually a categorical column
                if m in registry.categoricals:
                    select_parts.append(f"{m} as {m}")
                else:
                    # Numeric aggregation
                    is_rate_col = any(keyword in m.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
                    if is_rate_col and op in ["SUM", "AVERAGE", "AVG"]:
                        select_parts.append(f"AVG({m}) as {m}")
                    else:
                        select_parts.append(f"SUM({m}) as {m}")
            sql_select = ", ".join(select_parts)
    where_str = " AND ".join(where_clauses)
    return where_str, metric_cols, tuple(params), sql_select, sql_group_by, sql_order_by

def levenshtein_dist(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_dist(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

async def federated_query_processor(bp: Blueprint, raw_query: str, parsing_metadata: Optional[Dict] = None) -> Dict[str, Any]:
    registry = MetadataRegistry.get_instance()
    
    # Case 9: Timeframe Boundary Guard
    tf_list = bp.timeframes or ([bp.timeframe] if bp.timeframe else [])
    if tf_list:
        allowed_years = set(registry.categoricals.get('fy_year', {}).get('values', []))
        if allowed_years:
            for tf in tf_list:
                val_str = str(tf.get('value', '')).replace("FY", "")
                if val_str.isdigit():
                    y_int = int(val_str)
                    if y_int not in allowed_years:
                        logger.warning(f"⚠️ Validation Blocked: Year {y_int} is out of database bounds.")
                        return {
                            "status": "error",
                            "message": f"Ambiguity or error: The requested year {y_int} is outside the available database bounds ({min(allowed_years)} - {max(allowed_years)}).",
                            "results": []
                        }
                        
    # 2. Zero-Trust Dynamic Entity Validation & Fuzzy Recovery
    client_unknowns = (parsing_metadata or {}).get("unknown_tokens", [])
    filter_values = [str(f['value']).lower() for f in bp.filters]
    
    # Meaningful words check (ignore actions and fluff)
    meaningful_unknowns = [u.lower() for u in client_unknowns if len(u) > 2 and u.lower() not in ['across', 'sites', 'all', 'from', 'year', 'than', 'between', 'and', 'id', 'project', 'is', 'the', 'of', 'for']]
    
    candidates = []
    candidates.extend(POWER_PLANTS)
    for cat in registry.categoricals.values():
        candidates.extend([str(v) for v in cat["values"]])
    candidate_map = {c.lower(): c for c in set(candidates)}

    unhandled_entities = []
    for u in meaningful_unknowns:
        if u not in filter_values and u not in registry.metrics:
            # Direct/Substring match to a power plant
            matched_plant = None
            for p in POWER_PLANTS:
                if u == p.lower() or (len(u) >= 4 and (u in p.lower() or p.lower() in u)):
                    matched_plant = p
                    break
            
            if matched_plant:
                bp.filters.append({"column": "plant", "value": matched_plant})
                filter_values.append(matched_plant.lower())
                logger.info(f"🔮 Direct Site Recovery: mapped '{u}' -> filter 'plant' = '{matched_plant}'")
                continue
                
            # Perform Case 8 Fuzzy Match
            found_match = None
            for c_lower, c_orig in candidate_map.items():
                dist = levenshtein_dist(u, c_lower)
                max_dist = 2 if len(u) > 4 else 1
                if dist <= max_dist:
                    found_match = c_orig
                    break
            
            if found_match:
                # Resolve target filter column name
                target_col = "plant" if found_match.lower() in [p.lower() for p in POWER_PLANTS] else None
                if not target_col:
                    for col_name, cat in registry.categoricals.items():
                        if found_match in cat["values"]:
                            target_col = "project_type" if col_name == "department" else col_name
                            break
                if target_col:
                    bp.filters.append({"column": target_col, "value": found_match})
                    filter_values.append(found_match.lower())
                    logger.info(f"🔮 Case 8 Fuzzy Recovery: mapped '{u}' -> filter '{target_col}' = '{found_match}'")
                    continue
            
            unhandled_entities.append(u)

    if unhandled_entities and not ("across" in raw_query.lower() or "all sites" in raw_query.lower()):
        return {"status": "clarification_required", "message": f"Query contains unrecognized entities: {', '.join(unhandled_entities)}. Execution halted.", "results": []}

    # 1. Targeted Routing (Subset of Plants)
    target_plants = [f['value'] for f in bp.filters if f['column'] == 'plant']
    plants_to_query = [p for p in target_plants if p in POWER_PLANTS]
    if not plants_to_query: plants_to_query = POWER_PLANTS

    # 2. Detect "Comparison" intent (explicit or implicit multi-site)
    is_across_sites = ("across" in raw_query.lower() or "all sites" in raw_query.lower() or "compare" in raw_query.lower())
    is_multi_site = len(plants_to_query) > 1 and len(plants_to_query) < len(POWER_PLANTS)
    force_comparison = is_across_sites or is_multi_site

    # 3. Detect Project Profile request
    project_id_filter = next((f['value'] for f in bp.filters if f['column'] == 'project_id'), None)
    is_profile_request = project_id_filter is not None and not bp.metrics
    
    where_str, metric_cols, params, sql_sel, sql_grp, sql_ord = build_federated_query_parts(bp)
    
    # Force full row retrieval for Project Profile requests
    if is_profile_request:
        sql = f"SELECT * FROM {{table_name}} {'WHERE ' + where_str if where_str else ''} {sql_ord}".strip()
    else:
        sql = f"SELECT {sql_sel} FROM {{table_name}} {'WHERE ' + where_str if where_str else ''} {sql_grp} {sql_ord}".strip()
    
    tasks = [run_query_on_single_db(plant, sql, params) for plant in plants_to_query]
    db_results = await asyncio.gather(*tasks)

    # Aggregation / Full Result Processing
    if is_profile_request:
        results = []
        for res in db_results: results.extend(res)
        return {
            "status": "success", 
            "results": results, 
            "sql_query": sql.replace("{table_name}", "metrics_site_X"),
            "unit": "RawData",
            "metadata": {"mode": "Profile", "sources": len(plants_to_query)}
        }

    # ... existing aggregation ...
    metric_key = metric_cols[0]
    if force_comparison:
        results = [{"label": p.replace("_", " ").title(), metric_key: round(sum([r.get(metric_key) or 0 for r in res]), 2)} 
                   for p, res in zip(plants_to_query, db_results) if sum([r.get(metric_key) or 0 for r in res]) > 0]
        return {"status": "success", "results": results, "sql_query": "Targeted Multi-Site Comparison", "unit": "USD", "metadata": {"mode": "Site Comparison", "sources": len(plants_to_query)}}

    if sql_grp:
        aggregated_map = {}
        for res_list in db_results:
            for row in res_list:
                lbl = row['label']
                if lbl not in aggregated_map: aggregated_map[lbl] = {m: 0.0 for m in metric_cols}
                for m in metric_cols: aggregated_map[lbl][m] += (row.get(m) or 0)
        results = [{"label": k, **{m: round(v, 2) for m, v in ms.items()}} for k, ms in sorted(aggregated_map.items()) if any(v > 0 for v in ms.values())]
        
        if ("growth" in raw_query.lower() or "change" in raw_query.lower()) and len(results) > 1:
            for i in range(1, len(results)):
                prev = results[i-1][metric_key]
                if prev > 0: results[i]['growth_pct'] = round(((results[i][metric_key] - prev) / prev) * 100, 2)
                else: results[i]['growth_pct'] = 100.0 if results[i][metric_key] > 0 else 0.0
    else:
        total = sum([res[0].get(metric_key) or 0 for res in db_results if res])
        results = [{metric_key: round(total, 2)}] if total > 0 else []

    return {"status": "success", "results": results, "sql_query": sql.replace("{table_name}", "metrics_site_X"), "unit": "USD", "metadata": {"sources": len(plants_to_query)}}

# --- FastAPI App ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

async def call_ollama_fallback(raw_query: str) -> Blueprint:
    registry = MetadataRegistry.get_instance()
    system_prompt = (
        "You are a high-precision SQL query assistant for AGEL project tracking. "
        "Strictly map query to JSON blueprint. "
        f"Metrics: {list(registry.metrics.keys())}. "
        f"Sites: {POWER_PLANTS}. "
        "Map 'grand blue'/'grand' to 'grand_gulf'. Map 'digital' to project_type filter 'digital'. "
        "If a specific Project ID (PRJ-...) is requested, set operation to 'FULL_DETAILS'."
    )
    resp_text = ""
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": raw_query, "system": system_prompt, "stream": False, "format": "json"})
            resp_text = resp.json().get('response', '').strip()
    except Exception as e:
        logger.error(f"Ollama connection error: {e}")
        return Blueprint(metrics=["revenue"])
        
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
        logger.warning(f"Failed to parse cleaned LLM JSON: {e}")
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
        for possible_op in ["FULL_DETAILS", "BREAKDOWN", "GRAPH", "TREND", "COMPARE", "SUM", "AVERAGE", "MIN", "MAX"]:
            if possible_op.lower() in raw_query.lower() or possible_op.lower() in resp_text.lower():
                bp_data["operation"] = possible_op
                break
                
    # Map metrics
    metrics_list = data.get("metrics") or data.get("metric")
    if isinstance(metrics_list, str):
        metrics_list = [metrics_list]
    if isinstance(metrics_list, list):
        for m in metrics_list:
            if m and isinstance(m, str) and m in registry.metrics:
                bp_data["metrics"].append(m)
                
    if not bp_data["metrics"]:
        for m in registry.metrics:
            if m.lower() in raw_query.lower():
                bp_data["metrics"].append(m)
        if not bp_data["metrics"] and bp_data["operation"] != "FULL_DETAILS":
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
    for col_name, cat in registry.categoricals.items():
        val = data.get(col_name)
        if val and isinstance(val, str):
            for allowed in cat["values"]:
                if val.lower() == allowed.lower():
                    bp_data["filters"].append({"column": col_name, "value": allowed})
                    break

    return Blueprint(**bp_data)

@app.post("/api/query")
async def handle_query(payload: QueryBlueprintPayload):
    start = time.perf_counter()
    bp = payload.blueprint
    if payload.force_llm or not bp or not bp.metrics: 
        bp = await call_ollama_fallback(payload.raw_query)
    data = await federated_query_processor(bp, payload.raw_query, payload.parsing_metadata)
    data["metadata"] = {**data.get("metadata", {}), "backend_ms": (time.perf_counter() - start) * 1000, "engine": "LLM" if payload.force_llm else "Hybrid"}
    return data

@app.get("/api/metadata")
def get_metadata():
    registry = MetadataRegistry.get_instance()
    return {"metrics": list(registry.metrics.keys()), "plants": POWER_PLANTS, "categoricals": {k: list(v["values"]) for k,v in registry.categoricals.items()}}

@app.get("/")
def health(): return {"status": "online"}
