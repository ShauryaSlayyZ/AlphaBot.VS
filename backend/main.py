
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

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance._initialized = False
            cls._instance.metrics = {}
            cls._instance.categoricals = {}
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
        for col in cols:
            name, col_type = col[1], col[2].upper()
            if name in ['revenue', 'profit', 'expenses', 'headcount', 'salary', 'tax_liability', 'asset_value', 'operating_cost', 'marketing_spend', 'customer_count']:
                self.metrics[name] = {"column": name, "type": col_type}
            elif 'VARCHAR' in col_type or name in ['department', 'region']:
                self.categoricals[name] = {"values": set()}
        conn.close()

        self._initialized = True
        logger.info(f"✅ Singleton Registry Initialized. Metrics: {list(self.metrics.keys())}")

# --- Pydantic Models ---
class Blueprint(BaseModel):
    operation: str = "SUM"
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
    
    loop = asyncio.get_event_loop()
    def query():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            # Find table name dynamically for this DB
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
            table_name = cursor.fetchone()[0]
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
        if f['column'] == 'plant':
            continue
        where_clauses.append(f"{f['column']} = ?")
        params.append(f['value'])

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
        has_dept = any(f['column'] == 'department' for f in bp.filters)
        has_region = any(f['column'] == 'region' for f in bp.filters)
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
        has_dept_filter = any(f['column'] == 'department' for f in bp.filters)
        has_region_filter = any(f['column'] == 'region' for f in bp.filters)
        
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
        if f['column'] == 'plant':
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

    # Run queries in parallel
    tasks = [run_query_on_single_db(plant, sql_to_run, params) for plant in plants_to_query]
    results_per_db = await asyncio.gather(*tasks)

    # Handle aggregation based on operation type
    is_grouped = bool(sql_group_by)
    group_by_plant = (op == "BREAKDOWN" and 
                      any(f['column'] == 'department' for f in bp.filters) and 
                      any(f['column'] == 'region' for f in bp.filters))
                      
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
        
    return {
        "status": "success",
        "results": results,
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
    timeframe: Optional[Dict[str, str]] = None

async def call_ollama_fallback(raw_query: str) -> Blueprint:
    registry = MetadataRegistry.get_instance()
    system_prompt = f"Return ONLY JSON. Valid Metrics: {list(registry.metrics.keys())}."
    json_prompt = {"query": raw_query, "response_format": {"metrics": ["string"], "filters": [{"column": "string", "value": "string"}]}}

    async with httpx.AsyncClient(timeout=40.0) as client:
        try:
            resp = await client.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": json.dumps(json_prompt), "system": system_prompt, "stream": False, "format": "json"})
            validated_data = LLMBlueprintResponse(**json.loads(resp.json()['response']))
            return Blueprint(**validated_data.dict())
        except Exception as e:
            logger.error(f"Fallback AI Error: {e}")
            return Blueprint()

@app.post("/api/query")
async def handle_query(payload: QueryBlueprintPayload):
    start_time = time.perf_counter()
    logger.debug(f"handle_query: incoming payload = {payload}")
    blueprint = payload.blueprint
    
    # Fallback to Ollama only if the blueprint is completely empty or unparsed
    if not blueprint or (not blueprint.metrics and not blueprint.filters and not blueprint.operation):
        blueprint = await call_ollama_fallback(payload.raw_query)
        logger.debug(f"handle_query: fallback blueprint = {blueprint}")
        
    if not blueprint:
        blueprint = Blueprint()
        
    if not blueprint.metrics:
        has_dept = any(f['column'] == 'department' for f in blueprint.filters)
        has_region = any(f['column'] == 'region' for f in blueprint.filters)
        op = blueprint.operation.upper() if blueprint.operation else "SUM"
        if op == "BREAKDOWN" and has_dept and has_region:
            registry = MetadataRegistry.get_instance()
            blueprint.metrics = list(registry.metrics.keys())
        else:
            blueprint.metrics = ["revenue"]

    logger.debug(f"handle_query: passing blueprint to processor = {blueprint}")
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
