
import time
import sqlite3
import json
import httpx
import logging
import asyncio
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

# --- Federated Configuration ---
POWER_PLANTS = [
    "diablo_canyon", "three_mile_island", "palo_verde", 
    "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"
]
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3.5:3.8b"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alphabot-federated-engine")

# --- Metadata Registry (Federated Model) ---
class MetadataRegistry:
    _instance = None

    def __init__(self):
        self.metrics = {}       # e.g., 'revenue': {'column': 'revenue', 'type': 'NUMERIC'}
        self.categoricals = {}  # e.g., 'department': {'values': {'sales', 'digital', ...}}
        self.table_names = {}   # e.g., 'diablo_canyon': 'metrics_diablo_canyon'
        self._initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.initialize()
        return cls._instance

    def initialize(self):
        if self._initialized:
            return
        
        logger.info("🚀 Initializing Singleton Metadata Registry...")
        self.metrics.clear()
        self.categoricals.clear()

        # Schema introspection from the first plant db
        sample_db = os.path.join(BASE_DIR, f"{POWER_PLANTS[0]}.db")
        if not os.path.exists(sample_db):
            logger.error(f"FATAL: Database {sample_db} not found.")
            return
        
        conn = sqlite3.connect(sample_db)
        cursor = conn.cursor()
        # Find the table dynamically
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
        table_name = cursor.fetchone()[0]
        
        cursor.execute(f"PRAGMA table_info({table_name})")
        cols = cursor.fetchall()
        
        cat_columns = []
        for col in cols:
            name, col_type = col[1], col[2].upper()
            if name in ['revenue', 'profit', 'expenses', 'headcount', 'salary', 'tax_liability', 'asset_value', 'operating_cost', 'marketing_spend', 'customer_count']:
                self.metrics[name] = {"column": name, "type": col_type}
            elif 'VARCHAR' in col_type or name in ['department', 'region']:
                self.categoricals[name] = {"values": set()}
                cat_columns.append(name)
        conn.close()

        # Add plant explicitly since it's used for routing
        self.categoricals["plant"] = {"values": set(POWER_PLANTS)}

        # Fully analyze all databases to extract exact unique names
        for plant in POWER_PLANTS:
            db_path = os.path.join(BASE_DIR, f"{plant}.db")
            if not os.path.exists(db_path):
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
                local_table_name = cursor.fetchone()[0]
                self.table_names[plant] = local_table_name
                for col in cat_columns:
                    cursor.execute(f"SELECT DISTINCT {col} FROM {local_table_name} WHERE {col} IS NOT NULL")
                    for row in cursor.fetchall():
                        if row[0]:
                            self.categoricals[col]["values"].add(str(row[0]))
                conn.close()
            except Exception as e:
                logger.warning(f"⚠️ Could not extract values from {plant}.db: {e}")

        self._initialized = True
        logger.info(f"✅ Singleton Registry Initialized. Metrics: {list(self.metrics.keys())}")

# --- Pydantic Models ---
class Blueprint(BaseModel):
    operation: Optional[str] = "SUM"
    metrics: List[str] = []
    filters: List[Dict[str, str]] = []
    timeframe: Optional[Dict[str, str]] = None
    comparison: Optional[Dict[str, Any]] = None

class QueryBlueprintPayload(BaseModel):
    raw_query: str
    blueprint: Optional[Blueprint] = None

# --- Federated Query Engine ---
async def run_query_on_single_db(plant: str, sql: str, params: tuple) -> List[Dict]:
    """Runs a SQL query on a single power plant database file."""
    db_file = os.path.join(BASE_DIR, f"{plant}.db")
    if not os.path.exists(db_file): return []
    
    registry = MetadataRegistry.get_instance()
    table_name = registry.table_names.get(plant)
    if not table_name: return []

    loop = asyncio.get_event_loop()
    def query():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        
        # Performance PRAGMAs
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA mmap_size = 30000000000;")
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("PRAGMA cache_size = -64000;")

        cursor = conn.cursor()
        try:
            cursor.execute(sql.replace("{table_name}", table_name), params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    return await loop.run_in_executor(None, query)

def build_federated_query_parts(bp: Blueprint) -> (str, List[str], tuple, str, str, str):
    registry = MetadataRegistry.get_instance()
    where_clauses, params = [], []
    for f in bp.filters:
        # Exclude 'plant' from the SQL WHERE clause; it's handled by routing
        if f.get('column') == 'plant':
            continue
        if f.get('column') and f.get('value'):
            where_clauses.append(f"{f.get('column')} = ?")
            params.append(f.get('value'))

    if bp.timeframe and bp.timeframe.get('value'):
        val = str(bp.timeframe['value']).strip().upper()
        if "-" in val and len(val) == 10:
            where_clauses.append("DATE(record_date) = DATE(?)")
            params.append(val)
        elif "-" in val and len(val) > 10:
            where_clauses.append("record_date = ?")
            params.append(val)
        else:
            where_clauses.append("strftime('%Y', record_date) = ?")
            params.append(val.replace("FY", ""))

    metric_cols = [m for m in bp.metrics if m in registry.metrics]
    if not metric_cols:
        # For a breakdown query with department and region filters, default to all available metrics
        has_dept = any(f.get('column') == 'department' for f in bp.filters)
        has_region = any(f.get('column') == 'region' for f in bp.filters)
        op = bp.operation.upper() if bp.operation else "SUM"
        if op == "BREAKDOWN" and has_dept and has_region:
            metric_cols = list(registry.metrics.keys())
        else:
            metric_cols = ["revenue"]
            
    metric_key = metric_cols[0]

    # Handle grouping / graphing
    sql_select = ""
    sql_group_by = ""
    sql_order_by = ""
    
    op = bp.operation.upper() if bp.operation else "SUM"
    group_col = None
    
    if op in ["GRAPH", "TREND"]:
        if bp.timeframe and bp.timeframe.get('type') == 'year':
            group_col = "strftime('%Y-%m', record_date) as record_date"
            sql_group_by = "GROUP BY strftime('%Y-%m', record_date)"
            sql_order_by = "ORDER BY record_date ASC"
        else:
            group_col = "strftime('%Y', record_date) as record_date"
            sql_group_by = "GROUP BY strftime('%Y', record_date)"
            sql_order_by = "ORDER BY record_date ASC"
    elif op == "BREAKDOWN":
        has_dept_filter = any(f.get('column') == 'department' for f in bp.filters)
        has_region_filter = any(f.get('column') == 'region' for f in bp.filters)
        
        if has_dept_filter and not has_region_filter:
            group_col = "region"
            sql_group_by = "GROUP BY region"
        elif has_region_filter and not has_dept_filter:
            group_col = "department"
            sql_group_by = "GROUP BY department"
        elif not has_dept_filter and not has_region_filter:
            group_col = "department"
            sql_group_by = "GROUP BY department"
        # If both department and region filters are present, we will do plant grouping in python
        
    select_parts = []
    if group_col:
        select_parts.append(group_col)
    for m in metric_cols:
        select_parts.append(f"SUM({m}) as {m}")
        
    sql_select = ", ".join(select_parts)
    where_str = " AND ".join(where_clauses)
    return where_str, metric_cols, tuple(params), sql_select, sql_group_by, sql_order_by

async def federated_query_processor(bp: Blueprint, raw_query: str) -> Dict[str, Any]:
    """Queries databases in parallel (or specifically) and aggregates results."""
    where_str_part, metric_cols, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    metric_key = metric_cols[0]
    
    sql_where = f"WHERE {where_str_part}" if where_str_part else ""

    # Check if a specific plant is requested
    target_plant = None
    for f in bp.filters:
        if f.get('column') == 'plant':
            target_plant = f['value']
            break
            
    # Determine which plants to query
    plants_to_query = [target_plant] if target_plant and target_plant in POWER_PLANTS else POWER_PLANTS
    
    op = bp.operation.upper() if bp.operation else "SUM"
    
    # Construct query string
    query_parts = [f"SELECT {sql_select} FROM {{table_name}}", sql_where]
    if sql_group_by:
        query_parts.append(sql_group_by)
    if sql_order_by:
        query_parts.append(sql_order_by)
    sql_to_run = " ".join(part for part in query_parts if part)

    # --- NEW: Contextual KPI Query ---
    kpi_sql_select = "SUM(revenue) as revenue, SUM(profit) as profit, SUM(expenses) as expenses, SUM(headcount) as headcount"
    kpi_sql_to_run = f"SELECT {kpi_sql_select} FROM {{table_name}} {sql_where}".strip()

    # Run queries in parallel
    tasks = [run_query_on_single_db(plant, sql_to_run, params) for plant in plants_to_query]
    kpi_tasks = [run_query_on_single_db(plant, kpi_sql_to_run, params) for plant in plants_to_query]
    
    # Gather both sets of tasks
    all_results = await asyncio.gather(*(tasks + kpi_tasks))
    results_per_db = all_results[:len(tasks)]
    kpi_results_per_db = all_results[len(tasks):]

    # Handle aggregation based on operation type
    is_grouped = bool(sql_group_by)
    group_by_plant = (op == "BREAKDOWN" and 
                      any(f.get('column') == 'department' for f in bp.filters) and 
                      any(f.get('column') == 'region' for f in bp.filters))
                      
    if group_by_plant:
        # Group by plant (return a row per plant with all metrics)
        aggregated_results = []
        for plant, res_list in zip(plants_to_query, results_per_db):
            row = {"plant": plant}
            for m in metric_cols:
                val = res_list[0][m] if res_list and res_list[0] and res_list[0].get(m) is not None else 0
                row[m] = round(val, 2)
            aggregated_results.append(row)
        results = aggregated_results
    elif is_grouped:
        # Aggregate results across databases
        aggregated_map = {}
        group_key_col = None
        for res_list in results_per_db:
            for row in res_list:
                # Find the grouping key (the string field, e.g. 'record_date', 'department', 'region')
                current_group_key_col = next((k for k, v in row.items() if isinstance(v, str)), None)
                if not current_group_key_col:
                    continue
                group_key_col = current_group_key_col
                group_val = row[group_key_col]
                
                if group_val not in aggregated_map:
                    aggregated_map[group_val] = {m: 0.0 for m in metric_cols}
                
                for m in metric_cols:
                    metric_val = row.get(m)
                    if metric_val is not None:
                        aggregated_map[group_val][m] += metric_val
                        
        if group_key_col:
            results = []
            for k, metrics_dict in sorted(aggregated_map.items()):
                row = {group_key_col: k}
                for m in metric_cols:
                    row[m] = round(metrics_dict[m], 2)
                results.append(row)
        else:
            results = []
    else:
        # Single value total aggregation (could have multiple metrics)
        row = {}
        for m in metric_cols:
            total = sum(res[0][m] for res in results_per_db if res and res[0] and res[0].get(m) is not None)
            row[m] = round(total, 2)
        results = [row]
        
    # Aggregate Contextual KPIs
    kpis = {"revenue": 0, "profit": 0, "expenses": 0, "headcount": 0}
    for res in kpi_results_per_db:
        if res and res[0]:
            kpis["revenue"] += res[0].get("revenue") or 0
            kpis["profit"] += res[0].get("profit") or 0
            kpis["expenses"] += res[0].get("expenses") or 0
            kpis["headcount"] += res[0].get("headcount") or 0

    return {
        "status": "success",
        "results": results,
        "kpis": kpis,
        "sql_query": sql_to_run.replace("{table_name}", "metrics_bus_unit_X"),
        "unit": "USD" if metric_key not in ['headcount', 'customer_count'] else "Units",
        "plants_queried": len(plants_to_query)
    }


# --- FastAPI App ---
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup
    MetadataRegistry.get_instance()
    yield
    # On shutdown
    pass

app = FastAPI(lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class LLMBlueprintResponse(BaseModel):
    metrics: List[str] = Field(default_factory=list)
    filters: List[Dict[str, str]] = Field(default_factory=list)
    timeframe: Optional[Dict[str, Optional[str]]] = None
    operation: Optional[str] = None

async def call_ollama_fallback(raw_query: str) -> Blueprint:
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

    json_prompt = f"Parse this query: {raw_query}"

    async with httpx.AsyncClient(timeout=40.0) as client:
        try:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL, 
                "prompt": json_prompt, 
                "system": system_prompt, 
                "stream": False, 
                "format": "json"
            })
            resp_dict = json.loads(resp.json()['response'])
            logger.info(f"🤖 Ollama raw response: {resp_dict}")
            validated_data = LLMBlueprintResponse(**resp_dict)
            
            # Map LLMBlueprintResponse to Blueprint safely, removing None values
            bp_args = {}
            if validated_data.operation is not None:
                bp_args["operation"] = validated_data.operation
            if validated_data.metrics:
                bp_args["metrics"] = [m for m in validated_data.metrics if m]
            if validated_data.filters:
                cleaned_filters = []
                for f in validated_data.filters:
                    if isinstance(f, dict):
                        cleaned_f = {k: v for k, v in f.items() if v is not None}
                        if cleaned_f:
                            cleaned_filters.append(cleaned_f)
                bp_args["filters"] = cleaned_filters
            if validated_data.timeframe:
                if isinstance(validated_data.timeframe, dict):
                    bp_args["timeframe"] = {k: v for k, v in validated_data.timeframe.items() if v is not None}
            
            return Blueprint(**bp_args)
        except Exception as e:
            logger.error(f"Fallback AI Error: {e}")
            return Blueprint()

@app.post("/api/query")
async def handle_query(payload: QueryBlueprintPayload):
    start_time = time.perf_counter()
    logger.info(f"📥 Received query: '{payload.raw_query}'")
    logger.debug(f"handle_query: incoming payload = {payload}")
    blueprint = payload.blueprint
    
    # Fallback to Ollama only if the blueprint is completely empty or unparsed
    if not blueprint or (not blueprint.metrics and not blueprint.filters and not blueprint.operation):
        logger.info(f"🤖 Calling Ollama to parse: '{payload.raw_query}'")
        blueprint = await call_ollama_fallback(payload.raw_query)
        logger.info(f"📋 Ollama returned: {blueprint}")
        
    if not blueprint:
        logger.warning(f"⚠️ No blueprint from Ollama, creating default")
        blueprint = Blueprint()
        
    # Normalize filters to ensure standard format
    normalized_filters = []
    for f in blueprint.filters:
        if 'column' in f and 'value' in f:
            val_normalized = str(f['value']).replace(' ', '_')
            if val_normalized in POWER_PLANTS:
                f['column'] = 'plant'
                f['value'] = val_normalized
            normalized_filters.append(f)
        else:
            for k, v in f.items():
                v_str = str(v)
                v_normalized = v_str.replace(' ', '_')
                if k in ['plant', 'department', 'region']:
                    if v_normalized in POWER_PLANTS:
                        k = 'plant'
                        v_str = v_normalized
                    normalized_filters.append({"column": k, "value": v_str})
    blueprint.filters = normalized_filters

    # --- Heuristic Reinforcement for 100% Robust Parsing ---
    import re
    raw_lower = payload.raw_query.lower()
    
    # 1. Operation Heuristics
    if "trend" in raw_lower or "over time" in raw_lower or "by year" in raw_lower or "graph" in raw_lower:
        blueprint.operation = "GRAPH"
    elif "breakdown" in raw_lower or "compare" in raw_lower or "by" in raw_lower:
        if not blueprint.operation or blueprint.operation.upper() not in ["GRAPH", "TREND"]:
            blueprint.operation = "BREAKDOWN"
            
    # 2. Metric Heuristics
    # Only override if metrics is empty or is the default "revenue" and the query does not ask for revenue
    if not blueprint.metrics or (blueprint.metrics == ["revenue"] and "revenue" not in raw_lower and "money" not in raw_lower and "earnings" not in raw_lower and "income" not in raw_lower):
        detected_metrics = []
        if "operating cost" in raw_lower or "operating expense" in raw_lower or "op cost" in raw_lower or "operating spend" in raw_lower:
            detected_metrics.append("operating_cost")
        elif "marketing spend" in raw_lower or "marketing cost" in raw_lower or "marketing expense" in raw_lower:
            detected_metrics.append("marketing_spend")
        elif "expense" in raw_lower or "spending" in raw_lower or "spend" in raw_lower or "cost" in raw_lower or "costs" in raw_lower:
            detected_metrics.append("expenses")
            
        if "tax" in raw_lower or "taxes" in raw_lower or "tax liability" in raw_lower or "taxation" in raw_lower:
            detected_metrics.append("tax_liability")
            
        if "asset" in raw_lower or "assets" in raw_lower:
            detected_metrics.append("asset_value")
            
        if "customer" in raw_lower or "client" in raw_lower or "user" in raw_lower:
            detected_metrics.append("customer_count")
            
        if "revenue" in raw_lower or "money" in raw_lower or "earnings" in raw_lower or "income" in raw_lower:
            if "profit" not in raw_lower:
                detected_metrics.append("revenue")
                
        if "profit" in raw_lower or "margin" in raw_lower:
            detected_metrics.append("profit")
            
        if "headcount" in raw_lower or "employee" in raw_lower or "people" in raw_lower or "staff" in raw_lower or "worker" in raw_lower:
            detected_metrics.append("headcount")
            
        if "salary" in raw_lower or "salaries" in raw_lower or "payroll" in raw_lower or "wage" in raw_lower:
            detected_metrics.append("salary")
            
        if detected_metrics:
            blueprint.metrics = detected_metrics

    # 3. Timeframe / Year Heuristics
    year_match = re.search(r'\b(202\d)\b', raw_lower)
    if year_match:
        year_val = year_match.group(1)
        blueprint.timeframe = {"type": "year", "value": year_val}
        
    # 4. Filters Heuristics (Department, Region, Plant)
    for dept in ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"]:
        if dept in raw_lower:
            if not any(f.get('column') == 'department' and f.get('value') == dept for f in blueprint.filters):
                blueprint.filters.append({"column": "department", "value": dept})
                
    for region in ["north", "south", "east", "west", "central"]:
        if region in raw_lower:
            if not any(f.get('column') == 'region' and f.get('value') == region for f in blueprint.filters):
                blueprint.filters.append({"column": "region", "value": region})
                
    for plant in POWER_PLANTS:
        plant_clean = plant.replace('_', ' ')
        if plant in raw_lower or plant_clean in raw_lower:
            if not any(f.get('column') == 'plant' and f.get('value') == plant for f in blueprint.filters):
                blueprint.filters.append({"column": "plant", "value": plant})
        
    if not blueprint.metrics:
        has_dept = any(f.get('column') == 'department' for f in blueprint.filters)
        has_region = any(f.get('column') == 'region' for f in blueprint.filters)
        op = blueprint.operation.upper() if blueprint.operation else "SUM"
        if op == "BREAKDOWN" and has_dept and has_region:
            registry = MetadataRegistry.get_instance()
            blueprint.metrics = list(registry.metrics.keys())
        else:
            logger.info(f"📊 No metrics specified, defaulting to revenue")
            blueprint.metrics = ["revenue"]

    logger.info(f"🔧 Final blueprint - Metrics: {blueprint.metrics}, Filters: {blueprint.filters}, Operation: {blueprint.operation}")
    execution_data = await federated_query_processor(blueprint, payload.raw_query)
    
    if execution_data["status"] == "success":
        num_plants = execution_data.get("plants_queried", len(POWER_PLANTS))
        execution_data["insights"] = {"summary": "Federated query successful.", "analysis": f"Aggregated from {num_plants} sources."}
    
    execution_data["metadata"] = {"backend_ms": (time.perf_counter() - start_time) * 1000}
    return execution_data

@app.get("/api/metadata")
def get_metadata():
    registry = MetadataRegistry.get_instance()
    return {"metrics": list(registry.metrics.keys()), "categoricals": {k: list(v["values"]) for k,v in registry.categoricals.items()}}

@app.get("/")
def health(): return {"status": "online"}
