
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3.5:3.8b"

def is_plant_db(db_path):
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False

try:
    db_files = [f for f in os.listdir(BASE_DIR) if f.endswith('.db')]
    discovered_plants = []
    for f in db_files:
        db_name = os.path.splitext(f)[0]
        if is_plant_db(os.path.join(BASE_DIR, f)):
            discovered_plants.append(db_name)
    POWER_PLANTS = sorted(discovered_plants)
except Exception:
    POWER_PLANTS = []

if not POWER_PLANTS:
    POWER_PLANTS = [
        "diablo_canyon", "three_mile_island", "palo_verde", 
        "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"
    ]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alphabot-federated-engine")

def extract_detected_years(text: str) -> List[str]:
    import re
    if not text:
        return []
    # Match any range of years 2020-2026 separated by to/through/thru/till/until or hyphen
    range_pattern = r'(?<!\d)(202[0-6])\s*(?:to|through|thru|\-|till|until)\s*(202[0-6])(?!\d)'
    ranges = re.findall(range_pattern, text.lower())
    
    # Also find all individual years 2020-2026
    all_years = re.findall(r'(?<!\d)(202[0-6])(?!\d)', text.lower())
    
    if not ranges:
        # No range detected, just return unique list of individual years preserving order
        seen = set()
        res = []
        for y in all_years:
            if y not in seen:
                seen.add(y)
                res.append(y)
        return res
        
    expanded = set()
    for start, end in ranges:
        s_val, e_val = int(start), int(end)
        if s_val <= e_val:
            for y in range(s_val, e_val + 1):
                expanded.add(str(y))
        else:
            for y in range(e_val, s_val + 1):
                expanded.add(str(y))
                
    # Also include any other individual years outside the ranges
    for y in all_years:
        expanded.add(y)
        
    # Return sorted list of years
    return sorted(list(expanded))


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
    filters: List[Dict[str, Any]] = []
    timeframe: Optional[Dict[str, Any]] = None
    comparison: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None
    sort_asc: Optional[bool] = None

class QueryBlueprintPayload(BaseModel):
    raw_query: str
    blueprint: Optional[Blueprint] = None

# --- Caching Layers ---
SEMANTIC_CACHE = {}  # Normalized Query String -> Blueprint
RESULT_CACHE = {}    # Stable Blueprint JSON String -> Query Response Dict

def normalize_query_key(raw_query: str) -> str:
    """Normalizes raw queries to ignore formatting, punctuation, and common stopwords for semantic similarity."""
    import re
    # Lowercase & remove punctuation/special characters
    cleaned = re.sub(r'[^\w\s]', ' ', raw_query.lower())
    # Tokenize & remove common stopwords/fillers
    stopwords = {
        "what", "is", "the", "of", "in", "for", "between", "and", "show", "get", "total",
        "trend", "trends", "over", "time", "at", "plant", "department", "region", "compare", 
        "a", "an", "year", "years", "graph", "to", "with", "by", "how"
    }
    tokens = [t for t in cleaned.split() if t and t not in stopwords]
    # Sort tokens to treat word-order changes as identical queries
    tokens.sort()
    return " ".join(tokens)

class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_end_of_word = False
        self.category = None # 'metric', 'department', 'region', 'plant'
        self.original_name = None

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str, category: str, original_name: str = None):
        node = self.root
        for char in word.lower():
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True
        node.category = category
        node.original_name = original_name or word

    def search_prefix(self, prefix: str) -> List[Dict[str, Any]]:
        node = self.root
        for char in prefix.lower():
            if char not in node.children:
                return []
            node = node.children[char]
        
        results = []
        self._collect(node, prefix.lower(), results)
        return results

    def _collect(self, node: TrieNode, path: str, results: List[Dict[str, Any]]):
        if node.is_end_of_word:
            results.append({
                "word": path,
                "category": node.category,
                "original_name": node.original_name
            })
        for char, child in node.children.items():
            self._collect(child, path + char, results)

SUGGESTIONS_TRIE = Trie()

def initialize_trie():
    # Metrics
    metrics = [
        ("revenue", "Revenue"),
        ("profit", "Profit"),
        ("expenses", "Expenses"),
        ("headcount", "Headcount"),
        ("salary", "Salary"),
        ("tax_liability", "Tax Liability"),
        ("asset_value", "Asset Value"),
        ("operating_cost", "Operating Cost"),
        ("marketing_spend", "Marketing Spend"),
        ("customer_count", "Customer Count")
    ]
    for key, name in metrics:
        SUGGESTIONS_TRIE.insert(key, "metric", name)
        for part in key.split('_'):
            if len(part) > 2:
                SUGGESTIONS_TRIE.insert(part, "metric", name)
                
    # Departments
    departments = ["sales", "digital", "marketing", "hr", "engineering", "finance", "support", "operations"]
    for d in departments:
        SUGGESTIONS_TRIE.insert(d, "department", d.capitalize())
        
    # Regions
    regions = ["north", "south", "east", "west", "central"]
    for r in regions:
        SUGGESTIONS_TRIE.insert(r, "region", r.capitalize())
        
    plants = POWER_PLANTS
    for p in plants:
        clean_p = p.replace('_', ' ')
        SUGGESTIONS_TRIE.insert(p, "plant", clean_p.title())
        for part in p.split('_'):
            if len(part) > 2:
                SUGGESTIONS_TRIE.insert(part, "plant", clean_p.title())

def extract_query_components(q: str):
    q_lower = q.lower()
    
    # 1. Detect metrics (complete or partial)
    detected_metrics = []
    metrics_map = {
        "revenue": "Revenue", "profit": "Profit", "expenses": "Expenses", 
        "headcount": "Headcount", "salary": "Salary", "tax_liability": "Tax Liability",
        "asset_value": "Asset Value", "operating_cost": "Operating Cost",
        "marketing_spend": "Marketing Spend", "customer_count": "Customer Count"
    }
    for key in metrics_map:
        clean_key = key.replace('_', ' ')
        if clean_key in q_lower or key in q_lower:
            detected_metrics.append((key, metrics_map[key]))
            
    # 2. Detect departments
    detected_depts = []
    all_depts = ["sales", "digital", "marketing", "hr", "engineering", "finance", "support", "operations"]
    for d in all_depts:
        if d in q_lower:
            if d == "marketing":
                marketing_as_metric_count = (
                    q_lower.count("marketing spend") + 
                    q_lower.count("marketing cost") + 
                    q_lower.count("marketing expense")
                )
                marketing_total_count = q_lower.count("marketing")
                if marketing_total_count > marketing_as_metric_count:
                    detected_depts.append(d.capitalize())
            else:
                detected_depts.append(d.capitalize())
            
    # 3. Detect regions
    detected_regions = []
    all_regions = ["north", "south", "east", "west", "central"]
    for r in all_regions:
        if r in q_lower:
            detected_regions.append(r.capitalize())
            
    detected_plants = []
    all_plants = POWER_PLANTS
    for p in all_plants:
        clean_p = p.replace('_', ' ')
        if p in q_lower or clean_p in q_lower:
            detected_plants.append(p)
            
    # 5. Detect years
    detected_years = extract_detected_years(q_lower)
    
    # 6. Check if the LAST token is incomplete and matches anything in Trie
    tokens = [t for t in q_lower.split() if t]
    last_token_match = None
    if tokens:
        last_token = tokens[-1]
        all_exact_matches = [m[0] for m in detected_metrics] + [d.lower() for d in detected_depts] + [r.lower() for r in detected_regions] + detected_plants
        if last_token not in all_exact_matches:
            prefix_results = SUGGESTIONS_TRIE.search_prefix(last_token)
            if prefix_results:
                last_token_match = prefix_results[0]
                
    if last_token_match:
        category = last_token_match["category"]
        name = last_token_match["original_name"]
        if category == "metric" and not any(m[1] == name for m in detected_metrics):
            metric_key = next((k for k, v in metrics_map.items() if v == name), None)
            if metric_key:
                detected_metrics.append((metric_key, name))
        elif category == "department" and name not in detected_depts:
            detected_depts.append(name)
        elif category == "region" and name not in detected_regions:
            detected_regions.append(name)
        elif category == "plant" and name.lower().replace(' ', '_') not in detected_plants:
            plant_key = next((p for p in all_plants if p.replace('_', ' ').title() == name or p == name), None)
            if plant_key:
                detected_plants.append(plant_key)
                
    return {
        "metrics": detected_metrics,
        "departments": detected_depts,
        "regions": detected_regions,
        "plants": detected_plants,
        "years": detected_years,
        "last_token_match": last_token_match
    }

def generate_intent_preview(q: str, components: dict):
    q_lower = q.lower()
    
    metric = "None"
    if components["metrics"]:
        metric = components["metrics"][0][1]
        
    dimension = "None"
    if "plant" in q_lower or components["plants"]:
        dimension = "Plant"
    elif "region" in q_lower or components["regions"]:
        dimension = "Region"
    elif "department" in q_lower or "dept" in q_lower or components["departments"]:
        dimension = "Department"
    elif "year" in q_lower or len(components["years"]) > 1:
        dimension = "Year"
        
    intent = "Sum"
    if any(w in q_lower for w in ["trend", "over time", "time-series", "monthly"]):
        intent = "Trend"
    elif any(w in q_lower for w in ["compare", "comparison", "versus", "vs", "between"]):
        intent = "Comparison"
    elif any(w in q_lower for w in ["top", "highest", "best", "lowest", "worst", "max", "min"]):
        intent = "Top N"
    elif any(w in q_lower for w in ["breakdown", "by", "split"]):
        intent = "Breakdown"
    elif dimension != "None":
        intent = "Breakdown"
        
    return {
        "intent": intent,
        "metric": metric,
        "dimension": dimension
    }

def get_levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return get_levenshtein_distance(s2, s1)
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

def correct_query_spelling(raw_query: str) -> str:
    import re
    # We want to split the query by word boundaries but preserve punctuation/spaces
    words = re.findall(r'\b[a-zA-Z]+\b', raw_query)
    
    corrected_query = raw_query
    
    stopwords = {
        "what", "is", "the", "of", "in", "for", "between", "and", "show", "get", "total",
        "trend", "trends", "over", "time", "at", "plant", "department", "region", "compare", 
        "a", "an", "year", "years", "graph", "to", "with", "by", "how", "vs", "versus"
    }
    
    # Dictionary of standard correct words in our schema
    valid_words = [
        "revenue", "profit", "expenses", "headcount", "salary", "operating", "cost", "marketing", "spend",
        "tax", "liability", "asset", "value", "customer", "count", "sales", "digital", "hr", 
        "engineering", "finance", "support", "operations", "north", "south", "east", "west", "central",
        "diablo", "canyon", "three", "mile", "island", "palo", "verde", "grand", "gulf", "vogtle",
        "hinkley", "point", "kashiwazaki", "darlington"
    ]
    
    for word in words:
        w_lower = word.lower()
        if w_lower in stopwords or w_lower in valid_words or len(w_lower) < 2:
            continue
            
        # Find best match in valid_words
        best_match = None
        min_dist = 999
        for valid in valid_words:
            # For short words like 'hr', only allow distance 1. For others, allow up to 2.
            max_allowed = 1 if len(w_lower) <= 3 else 2
            dist = get_levenshtein_distance(w_lower, valid)
            if dist <= max_allowed and dist < min_dist:
                min_dist = dist
                best_match = valid
                
        if best_match:
            replacement = best_match
            if word[0].isupper():
                replacement = best_match.capitalize()
            corrected_query = re.sub(r'\b' + word + r'\b', replacement, corrected_query)
            
    return corrected_query

def get_suggested_correction(raw_query: str) -> Optional[str]:
    import re
    # 1. Correct spelling typos first
    spelled_query = correct_query_spelling(raw_query)
    
    raw_lower = spelled_query.lower()
    # Check for years outside range using negative lookarounds
    years = re.findall(r'(?<!\d)(\d{4})(?!\d)', raw_lower)
    invalid_years = [y for y in years if not (2020 <= int(y) <= 2026)]
    if invalid_years:
        corrected = spelled_query
        for y in invalid_years:
            val = int(y)
            if val < 2020:
                corrected = re.sub(r'(?<!\d)' + y + r'(?!\d)', '2020', corrected)
            elif val > 2026:
                corrected = re.sub(r'(?<!\d)' + y + r'(?!\d)', '2026', corrected)
        return f"Did you mean: '{corrected}'?"
    
    # Check if query is completely unrecognized (gibberish/no matches)
    components = extract_query_components(spelled_query)
    has_structural = any(w in raw_lower for w in ["trend", "compare", "breakdown", "performance", "growth", "total", "top", "best", "worst", "plant", "plants"])
    if not (components["metrics"] or components["departments"] or components["regions"] or components["plants"] or components["years"] or has_structural):
        return "Try searching for: 'Revenue Trend', 'Profit by Region', or 'Department Performance'."
        
    # If spelling was corrected but no year error was found, suggest the spelling correction
    if spelled_query.strip().lower() != raw_query.strip().lower():
        return f"Did you mean: '{spelled_query}'?"
        
    return None

def parse_query_deterministically(raw_query: str) -> Optional[Dict[str, Any]]:
    """Deterministically parses common query patterns to bypass the LLM entirely."""
    raw_lower = raw_query.lower().strip()
    
    # Exact match for Suggested Business Questions
    if raw_lower in ["top revenue plants", "revenue trend", "profit by region", "department performance", "customer growth", "top plants", "top performing plants", "best plants", "worst plants"]:
        bp = Blueprint()
        confidence = 1.0
        intent = "unknown"
        
        if raw_lower == "top revenue plants":
            intent = "top_n"
            bp.metrics = ["revenue"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "plant"}
            bp.limit = 3
            bp.sort_asc = False
        elif raw_lower in ["top plants", "top performing plants", "best plants", "worst plants"]:
            intent = "top_n"
            bp.metrics = ["revenue", "profit", "expenses", "headcount"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "plant"}
            bp.limit = None
            bp.sort_asc = True if "worst" in raw_lower else False
        elif raw_lower == "revenue trend":
            intent = "trend"
            bp.metrics = ["revenue"]
            bp.operation = "GRAPH"
        elif raw_lower == "profit by region":
            intent = "breakdown"
            bp.metrics = ["profit"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "region"}
        elif raw_lower == "department performance":
            intent = "breakdown"
            bp.metrics = ["revenue"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "department"}
        elif raw_lower == "customer growth":
            intent = "trend"
            bp.metrics = ["customer_count"]
            bp.operation = "GRAPH"
            
        return {
            "blueprint": bp,
            "intent": intent,
            "confidence": confidence,
            "top_n_limit": bp.limit,
            "top_n_asc": bp.sort_asc
        }
    
    # 1. Identify Metrics (must have at least one metric to parse deterministically)
    detected_metrics = []
    if "operating cost" in raw_lower or "operating expense" in raw_lower or "op cost" in raw_lower or "operating spend" in raw_lower:
        detected_metrics.append("operating_cost")
    elif "marketing spend" in raw_lower or "marketing cost" in raw_lower or "marketing expense" in raw_lower:
        detected_metrics.append("marketing_spend")
    elif "expenses" in raw_lower or "spending" in raw_lower or "spend" in raw_lower or "cost" in raw_lower or "costs" in raw_lower:
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
        
    if not detected_metrics:
        return None
        
    bp = Blueprint()
    bp.metrics = detected_metrics
    
    # 2. Extract Year context — only 2020-2026 are valid data years
    import re
    all_years_in_query = re.findall(r'(?<!\d)(\d{4})(?!\d)', raw_lower)
    invalid_years = [y for y in all_years_in_query if not (2020 <= int(y) <= 2026)]
    if invalid_years:
        correction = get_suggested_correction(raw_query)
        err_msg = f"No data available for year(s): {', '.join(invalid_years)}. Available range: 2020-2026."
        if correction:
            err_msg += f" {correction}"
        return {"blueprint": None, "intent": "invalid_year", "confidence": 0.0,
                "error": err_msg,
                "top_n_limit": None, "top_n_asc": False}
    detected_years = extract_detected_years(raw_lower)
    
    # 3. Categorical Filters
    # Departments
    detected_depts = []
    for dept in ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"]:
        if re.search(rf'\b{dept}\b', raw_lower):
            if dept == "marketing":
                marketing_as_metric_count = (
                    raw_lower.count("marketing spend") + 
                    raw_lower.count("marketing cost") + 
                    raw_lower.count("marketing expense")
                )
                marketing_total_count = len(re.findall(r'\bmarketing\b', raw_lower))
                if marketing_total_count > marketing_as_metric_count:
                    detected_depts.append(dept)
            else:
                detected_depts.append(dept)
            
    # Regions
    detected_regions = []
    for region in ["north", "south", "east", "west", "central"]:
        if re.search(rf'\b{region}\b', raw_lower):
            detected_regions.append(region)
            
    # Plants
    detected_plants = []
    for plant in POWER_PLANTS:
        plant_clean = plant.replace('_', ' ')
        if re.search(rf'\b{re.escape(plant)}\b', raw_lower) or re.search(rf'\b{re.escape(plant_clean)}\b', raw_lower):
            detected_plants.append(plant)

    # 4. Intent Classification
    intent = "sum"
    confidence = 1.0
    
    # Comparison check
    is_compare_query = any(w in raw_lower for w in ["compare", "comparison", "versus", "vs", "between"])
    if is_compare_query or len(detected_years) > 1 or len(detected_depts) > 1 or len(detected_regions) > 1 or len(detected_plants) > 1:
        intent = "comparison"
        
    # Top N check
    is_top_n_query = any(w in raw_lower for w in ["top", "highest", "best", "lowest", "worst", "max", "min"])
    if is_top_n_query:
        intent = "top_n"
        
    # Trend check
    is_trend_query = any(w in raw_lower for w in ["trend", "trends", "over time", "graph", "time-series", "monthly"])
    if is_trend_query and intent != "comparison" and intent != "top_n":
        intent = "trend"
        
    # Breakdown check
    is_breakdown_query = any(w in raw_lower for w in ["breakdown", "by", "divided by", "split by"])
    if is_breakdown_query and intent == "sum":
        intent = "breakdown"

    # 5. Populate Blueprint based on Intent
    # Timeframe handling
    if len(detected_years) > 1:
        bp.comparison = {"type": "year", "values": list(dict.fromkeys(detected_years))}
        bp.timeframe = {"type": "years", "value": ",".join(list(dict.fromkeys(detected_years)))}
        bp.operation = "GRAPH"
    elif len(detected_years) == 1:
        bp.timeframe = {"type": "year", "value": detected_years[0]}
    elif any(w in raw_lower for w in ["monthly", "by month", "by months"]):
        bp.timeframe = {"type": "monthly"}

    # Filters adding
    for d in detected_depts:
        bp.filters.append({"column": "department", "value": d})
    for r in detected_regions:
        bp.filters.append({"column": "region", "value": r})
    for p in detected_plants:
        bp.filters.append({"column": "plant", "value": p})

    # Comparison details populating
    if intent == "comparison":
        bp.operation = "GRAPH" if (len(detected_years) > 1 or is_trend_query) else "BREAKDOWN"
        if len(detected_years) > 1:
            bp.comparison = {"type": "year", "values": list(dict.fromkeys(detected_years))}
        elif len(detected_depts) > 1:
            bp.comparison = {"type": "department", "values": detected_depts}
        elif len(detected_regions) > 1:
            bp.comparison = {"type": "region", "values": detected_regions}
        elif len(detected_plants) > 1:
            bp.comparison = {"type": "plant", "values": detected_plants}
        else:
            # Check if specific dimensions are requested
            dimension = None
            if any(w in raw_lower for w in ["by region", "across regions", "compare regions", "compare region", "region comparison", "by regions"]):
                dimension = "region"
            elif any(w in raw_lower for w in ["by department", "across departments", "compare departments", "compare department", "department comparison", "by dept", "by depts"]):
                dimension = "department"
            elif any(w in raw_lower for w in ["by plant", "across plants", "compare plants", "compare plant", "plant comparison"]):
                dimension = "plant"
            elif any(w in raw_lower for w in ["by year", "across years", "compare years", "compare year", "year comparison"]):
                dimension = "year"
                
            if dimension:
                bp.comparison = {"type": dimension}
            else:
                # Ambiguous comparison without multiple values
                confidence = 0.7
            
    # Top N / Breakdown details populating
    top_n_limit = None
    top_n_asc = False
    if intent == "top_n":
        bp.operation = "BREAKDOWN"
        # Determine the dimension to rank
        dimension = None
        # Check explicit rank subjects: top plants, top regions, top departments
        if re.search(r'\b(top|best|highest|lowest|worst|max|min)\s+(\d+\s+)?plants?\b', raw_lower) or any(w in raw_lower for w in ["top plant", "best plant", "worst plant"]):
            dimension = "plant"
        elif re.search(r'\b(top|best|highest|lowest|worst|max|min)\s+(\d+\s+)?regions?\b', raw_lower) or any(w in raw_lower for w in ["top region", "best region", "worst region"]):
            dimension = "region"
        elif re.search(r'\b(top|best|highest|lowest|worst|max|min)\s+(\d+\s+)?(departments?|depts?)\b', raw_lower) or any(w in raw_lower for w in ["top department", "best department", "worst department", "top dept"]):
            dimension = "department"
        else:
            # Fallback based on keywords, prioritizing "plant" if present
            if "plant" in raw_lower:
                dimension = "plant"
            elif "department" in raw_lower or "dept" in raw_lower:
                dimension = "department"
            elif "region" in raw_lower:
                dimension = "region"
            else:
                dimension = "department"
            
        bp.comparison = {"type": dimension}
        
        # Limit extraction
        limit_match = re.search(r'\b(top|best|highest|lowest|worst)\s+(\d+)\b', raw_lower)
        if limit_match:
            top_n_limit = int(limit_match.group(2))
        else:
            top_n_limit = 3  # default
            
        # Direction check
        if any(w in raw_lower for w in ["lowest", "worst", "min"]):
            top_n_asc = True
            
        bp.limit = top_n_limit
        bp.sort_asc = top_n_asc
            
    elif intent == "trend":
        bp.operation = "GRAPH"
        
    elif intent == "breakdown":
        bp.operation = "BREAKDOWN"
        # Find breakdown dimension
        dimension = None
        if "by department" in raw_lower or "by dept" in raw_lower:
            dimension = "department"
        elif "by region" in raw_lower:
            dimension = "region"
        elif "by plant" in raw_lower:
            dimension = "plant"
        elif "by year" in raw_lower:
            dimension = "year"
        elif "department" in raw_lower or "dept" in raw_lower:
            dimension = "department"
        elif "region" in raw_lower:
            dimension = "region"
        elif "plant" in raw_lower:
            dimension = "plant"
        elif "year" in raw_lower:
            dimension = "year"
            
        if dimension == "year":
            bp.operation = "GRAPH"
        elif dimension:
            bp.comparison = {"type": dimension}
        else:
            # Fallback based on filter context
            if detected_depts and not detected_regions:
                bp.comparison = {"type": "region"}
            elif detected_regions and not detected_depts:
                bp.comparison = {"type": "department"}
            else:
                bp.comparison = {"type": "department"}
                
    elif intent == "sum":
        bp.operation = "SUM"

    return {
        "blueprint": bp,
        "intent": intent,
        "confidence": confidence,
        "top_n_limit": top_n_limit,
        "top_n_asc": top_n_asc
    }

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
    
    # Group filters by column name
    from collections import defaultdict
    grouped_filters = defaultdict(list)
    for f in bp.filters:
        col = f.get('column')
        val = f.get('value')
        if col and val:
            # Validate categorical columns against metadata registry values
            if col in registry.categoricals:
                matching_val = next((v for v in registry.categoricals[col]['values'] if v.lower() == str(val).lower()), None)
                if matching_val:
                    grouped_filters[col].append(matching_val)
                else:
                    logger.warning(f"Ignoring filter {col}={val} as it is not in valid values.")
            else:
                logger.warning(f"Ignoring filter with invalid column: {col}={val}")
            
    where_clauses, params = [], []
    for col, values in grouped_filters.items():
        if col == 'plant':
            continue
        # Deduplicate values
        unique_vals = list(dict.fromkeys(values))
        if len(unique_vals) == 1:
            where_clauses.append(f"{col} = ?")
            params.append(unique_vals[0])
        else:
            placeholders = ", ".join("?" for _ in unique_vals)
            where_clauses.append(f"{col} IN ({placeholders})")
            params.extend(unique_vals)

    # Timeframe handling
    is_year_comparison = False
    comparison_years = []
    if bp.timeframe and bp.timeframe.get('value'):
        val = str(bp.timeframe['value']).strip().upper()
        if bp.timeframe.get('type') == 'years':
            is_year_comparison = True
            comparison_years = val.split(",")
            placeholders = ", ".join("?" for _ in comparison_years)
            where_clauses.append(f"strftime('%Y', record_date) IN ({placeholders})")
            params.extend(comparison_years)
        elif "-" in val and len(val) == 10:
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
        # Default fallback
        metric_cols = ["revenue"]
            
    metric_key = metric_cols[0]

    # Handle grouping / graphing
    sql_select = ""
    sql_group_by = ""
    sql_order_by = ""
    
    op = bp.operation.upper() if bp.operation else "SUM"
    
    if op in ["GRAPH", "TREND"]:
        if bp.comparison and bp.comparison.get('type'):
            comp_type = bp.comparison['type']
            if comp_type == 'year':
                sql_select = "strftime('%m', record_date) as record_date, strftime('%Y', record_date) as comparison_group"
                sql_group_by = "GROUP BY strftime('%m', record_date), strftime('%Y', record_date)"
                sql_order_by = "ORDER BY record_date ASC, comparison_group ASC"
            elif comp_type == 'plant':
                # Plant is handled in Python, not in SQL
                group_by_month = bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']
                if group_by_month:
                    sql_select = "strftime('%Y-%m', record_date) as record_date"
                    sql_group_by = "GROUP BY strftime('%Y-%m', record_date)"
                else:
                    sql_select = "strftime('%Y', record_date) as record_date"
                    sql_group_by = "GROUP BY strftime('%Y', record_date)"
                sql_order_by = "ORDER BY record_date ASC"
            else:
                comp_col = comp_type
                group_by_month = bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']
                if group_by_month:
                    sql_select = f"strftime('%Y-%m', record_date) as record_date, {comp_col} as comparison_group"
                    sql_group_by = f"GROUP BY strftime('%Y-%m', record_date), {comp_col}"
                else:
                    sql_select = f"strftime('%Y', record_date) as record_date, {comp_col} as comparison_group"
                    sql_group_by = f"GROUP BY strftime('%Y', record_date), {comp_col}"
                sql_order_by = "ORDER BY record_date ASC, comparison_group ASC"
        else:
            if bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']:
                sql_select = "strftime('%Y-%m', record_date) as record_date"
                sql_group_by = "GROUP BY strftime('%Y-%m', record_date)"
            else:
                sql_select = "strftime('%Y', record_date) as record_date"
                sql_group_by = "GROUP BY strftime('%Y', record_date)"
            sql_order_by = "ORDER BY record_date ASC"
    elif op == "BREAKDOWN":
        if bp.comparison and bp.comparison.get('type') and bp.comparison['type'] != 'year':
            comp_col = bp.comparison['type']
            if comp_col == 'plant':
                sql_select = ""
                sql_group_by = ""
                sql_order_by = ""
            else:
                sql_select = f"{comp_col} as {comp_col}"
                sql_group_by = f"GROUP BY {comp_col}"
                sql_order_by = f"ORDER BY 1 ASC"
        else:
            has_dept_filter = any(f.get('column') == 'department' and f.get('value') for f in bp.filters)
            has_region_filter = any(f.get('column') == 'region' and f.get('value') for f in bp.filters)
            
            if has_dept_filter and not has_region_filter:
                sql_select = "region as region"
                sql_group_by = "GROUP BY region"
            elif has_region_filter and not has_dept_filter:
                sql_select = "department as department"
                sql_group_by = "GROUP BY department"
            else:
                sql_select = "department as department"
                sql_group_by = "GROUP BY department"
            sql_order_by = "ORDER BY 1 ASC"
        
    select_parts = []
    if sql_select:
        select_parts.append(sql_select)
    for m in metric_cols:
        select_parts.append(f"SUM({m}) as {m}")
        
    sql_select_final = ", ".join(select_parts)
    where_str = " AND ".join(where_clauses)
    return where_str, metric_cols, tuple(params), sql_select_final, sql_group_by, sql_order_by

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

    # --- Contextual KPI Query ---
    default_metrics = {"revenue", "profit", "expenses", "headcount"}
    dynamic_metric = None
    for m in bp.metrics:
        if m not in default_metrics:
            dynamic_metric = m
            break

    kpi_sql_select = "SUM(revenue) as revenue, SUM(profit) as profit, SUM(expenses) as expenses, SUM(headcount) as headcount"
    if dynamic_metric:
        kpi_sql_select += f", SUM({dynamic_metric}) as {dynamic_metric}"
    kpi_sql_to_run = f"SELECT {kpi_sql_select} FROM {{table_name}} {sql_where}".strip()

    # Run queries in parallel
    tasks = [run_query_on_single_db(plant, sql_to_run, params) for plant in plants_to_query]
    kpi_tasks = [run_query_on_single_db(plant, kpi_sql_to_run, params) for plant in plants_to_query]
    
    # Gather both sets of tasks
    all_results = await asyncio.gather(*(tasks + kpi_tasks))
    results_per_db = all_results[:len(tasks)]
    kpi_results_per_db = all_results[len(tasks):]

    # If comparison is by plant and it's a trend/graph query, inject comparison_group in Python
    if bp.comparison and bp.comparison.get('type') == 'plant' and op in ["GRAPH", "TREND"]:
        for plant, res_list in zip(plants_to_query, results_per_db):
            for row in res_list:
                row['comparison_group'] = plant

    # Handle aggregation based on operation type
    is_grouped = bool(sql_group_by)
    group_by_plant = (
        (op == "BREAKDOWN" and bp.comparison and bp.comparison.get('type') == 'plant') or
        (op == "BREAKDOWN" and 
         any(f.get('column') == 'department' and f.get('value') for f in bp.filters) and 
         any(f.get('column') == 'region' and f.get('value') for f in bp.filters))
    )
                      
    if group_by_plant:
        # Group by plant (return a row per plant with all metrics)
        aggregated_results = []
        for plant, res_list in zip(plants_to_query, results_per_db):
            row = {"plant": plant, "record_date": plant}
            for m in metric_cols:
                val = res_list[0][m] if res_list and res_list[0] and res_list[0].get(m) is not None else 0
                row[m] = round(val, 2)
            aggregated_results.append(row)
        results = aggregated_results
    elif is_grouped:
        # Check if result set has 'comparison_group'
        has_comparison_group = False
        for res_list in results_per_db:
            if res_list and len(res_list) > 0 and 'comparison_group' in res_list[0]:
                has_comparison_group = True
                break
                
        if has_comparison_group:
            # Pivot comparison results (long to wide)
            aggregated_map = {}
            for res_list in results_per_db:
                for row in res_list:
                    rec_date = row.get('record_date')
                    comp_group = row.get('comparison_group')
                    if rec_date is None or comp_group is None:
                        continue
                    
                    if rec_date not in aggregated_map:
                        aggregated_map[rec_date] = {}
                    if comp_group not in aggregated_map[rec_date]:
                        aggregated_map[rec_date][comp_group] = {m: 0.0 for m in metric_cols}
                        
                    for m in metric_cols:
                        val = row.get(m)
                        if val is not None:
                            aggregated_map[rec_date][comp_group][m] += val
                            
            results = []
            for rec_date, comp_dict in sorted(aggregated_map.items()):
                row_data = {"record_date": rec_date}
                for comp_group, metrics_dict in comp_dict.items():
                    if len(metric_cols) == 1:
                        row_data[str(comp_group)] = round(metrics_dict[metric_cols[0]], 2)
                    else:
                        for m in metric_cols:
                            row_data[f"{comp_group}_{m}"] = round(metrics_dict[m], 2)
                results.append(row_data)
        else:
            # Standard aggregation across databases
            aggregated_map = {}
            group_key_col = None
            for res_list in results_per_db:
                for row in res_list:
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
        # Single value total aggregation
        row = {}
        for m in metric_cols:
            total = sum(res[0][m] for res in results_per_db if res and res[0] and res[0].get(m) is not None)
            row[m] = round(total, 2)
        results = [row]
        
    # Aggregate Contextual KPIs
    kpis = {"revenue": 0, "profit": 0, "expenses": 0, "headcount": 0}
    if dynamic_metric:
        kpis[dynamic_metric] = 0
        
    for res in kpi_results_per_db:
        if res and res[0]:
            kpis["revenue"] += res[0].get("revenue") or 0
            kpis["profit"] += res[0].get("profit") or 0
            kpis["expenses"] += res[0].get("expenses") or 0
            kpis["headcount"] += res[0].get("headcount") or 0
            if dynamic_metric:
                kpis[dynamic_metric] += res[0].get(dynamic_metric) or 0

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
    initialize_trie()
    
    # Pre-cache Suggested Business Questions
    logger.info("⚡ Pre-caching Suggested Business Questions...")
    suggested_queries = [
        "Top Revenue Plants",
        "Revenue Trend",
        "Profit by Region",
        "Department Performance",
        "Customer Growth"
    ]
    for q in suggested_queries:
        try:
            await handle_query(QueryBlueprintPayload(raw_query=q))
        except Exception as e:
            logger.warning(f"⚠️ Failed to pre-cache '{q}': {e}")
            
    logger.info("✅ Suggested Business Questions pre-cached successfully!")
    yield
    # On shutdown
    pass

app = FastAPI(lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class LLMBlueprintResponse(BaseModel):
    metrics: List[str] = Field(default_factory=list)
    filters: List[Dict[str, Any]] = Field(default_factory=list)
    timeframe: Optional[Any] = None
    operation: Optional[Union[str, List[str]]] = None

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
                if isinstance(validated_data.operation, list):
                    bp_args["operation"] = validated_data.operation[0] if validated_data.operation else "SUM"
                else:
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
                elif isinstance(validated_data.timeframe, list):
                    for item in validated_data.timeframe:
                        if isinstance(item, dict):
                            bp_args["timeframe"] = {k: v for k, v in item.items() if v is not None}
                            break
            
            return Blueprint(**bp_args)
        except Exception as e:
            logger.error(f"Fallback AI Error: {e}")
            return Blueprint()

@app.get("/api/suggest")
def get_suggestions(q: Optional[str] = ""):
    start_time = time.perf_counter()
    
    # Clean input
    q = q or ""
    q_trimmed = q.strip()
    
    # If empty, return default business questions
    if not q_trimmed:
        return {
            "suggestions": {
                "metrics": [],
                "analysis": [
                    "Top Revenue Plants",
                    "Revenue Trend",
                    "Profit by Region",
                    "Department Performance",
                    "Customer Growth"
                ],
                "comparisons": []
            },
            "preview": None,
            "latency_ms": (time.perf_counter() - start_time) * 1000
        }
        
    # Correct typos in the prefix to match correctly
    q_spelled = correct_query_spelling(q_trimmed)
    components = extract_query_components(q_spelled)
    
    # Generate contextual completions
    completions = []
    q_lower = q_spelled.lower()
    
    # Year-specific suggestion rules
    detected_years = extract_detected_years(q_lower)
    
    if len(detected_years) >= 2:
        return {
            "suggestions": {
                "metrics": [],
                "analysis": [],
                "comparisons": []
            },
            "preview": generate_intent_preview(q_spelled, components),
            "latency_ms": (time.perf_counter() - start_time) * 1000
        }
        
    # Check if query ends with a year and range/list connector
    import re
    m_conn = re.search(r'\b(202[0-6])\s+(and|to|through|thru|\-|till|until)\s*$', q_lower)
    if m_conn:
        y1_str = m_conn.group(1)
        conn = m_conn.group(2)
        y1 = int(y1_str)
        completions = []
        for y in range(2020, 2027):
            if y == y1:
                continue
            if conn in ["to", "through", "thru", "-", "till", "until"] and y < y1:
                continue
            prefix_part = q_trimmed[:m_conn.start()]
            completions.append(f"{prefix_part}{y1_str} {conn} {y}")
            
        return {
            "suggestions": {
                "metrics": [],
                "analysis": completions[:5],
                "comparisons": []
            },
            "preview": generate_intent_preview(q_spelled, components),
            "latency_ms": (time.perf_counter() - start_time) * 1000
        }
        
    # Check if query ends with a single year
    m_single = re.search(r'\b(202[0-6])\s*$', q_lower)
    if m_single:
        y1_str = m_single.group(1)
        y1 = int(y1_str)
        completions = []
        for y in [y1 + 1, 2026]:
            if 2020 <= y <= 2026 and y != y1:
                prefix_part = q_trimmed[:m_single.start()]
                completions.append(f"{prefix_part}{y1_str} and {y}")
                completions.append(f"{prefix_part}{y1_str} to {y}")
        for y in range(2020, 2027):
            if y != y1 and len(completions) < 5:
                prefix_part = q_trimmed[:m_single.start()]
                c_and = f"{prefix_part}{y1_str} and {y}"
                if c_and not in completions:
                    completions.append(c_and)
                if y > y1 and len(completions) < 5:
                    c_to = f"{prefix_part}{y1_str} to {y}"
                    if c_to not in completions:
                        completions.append(c_to)
                        
        return {
            "suggestions": {
                "metrics": [],
                "analysis": completions[:5],
                "comparisons": []
            },
            "preview": generate_intent_preview(q_spelled, components),
            "latency_ms": (time.perf_counter() - start_time) * 1000
        }
    
    has_metric = len(components["metrics"]) > 0
    has_dept = len(components["departments"]) > 0
    has_region = len(components["regions"]) > 0
    has_plant = len(components["plants"]) > 0
    has_year = len(components["years"]) > 0
    
    depts = ["Sales", "Digital", "Marketing", "HR"]
    regions = ["North", "South", "East", "West", "Central"]
    years = ["2023", "2024", "2025", "2026"]
    metrics = ["Revenue", "Profit", "Expenses", "Headcount"]
    
    def add_comp(prefix, connector, suffix):
        p_clean = re.sub(r'[\s,;:?!\-\(\)]+$', '', prefix)
        conn_lower = connector.lower().strip()
        
        if not conn_lower:
            return f"{p_clean} {suffix}"
            
        if re.search(r'\b' + re.escape(conn_lower) + r'$', p_clean.lower()):
            return f"{p_clean} {suffix}"
        else:
            return f"{p_clean} {connector} {suffix}"

    is_comparison = any(w in q_lower for w in ["compare", "vs", "versus"])
    
    if is_comparison:
        if not has_metric:
            for m in metrics:
                completions.append(add_comp(q_spelled, "in", m.lower()))
        if not has_year:
            for y in years:
                completions.append(add_comp(q_spelled, "in", y))
    else:
        if has_metric:
            if not (has_dept or has_region or has_plant or has_year):
                for d in depts:
                    completions.append(add_comp(q_spelled, "in", d))
                for r in regions:
                    completions.append(add_comp(q_spelled, "in", r))
                for y in years:
                    completions.append(add_comp(q_spelled, "in", y))
            elif (has_dept or has_region or has_plant) and not has_year:
                for y in years:
                    completions.append(add_comp(q_spelled, "in", y))
        elif has_dept or has_region or has_plant:
            if not has_metric:
                for m in metrics:
                    completions.append(add_comp(q_spelled, "in", m.lower()))
                for y in years:
                    completions.append(add_comp(q_spelled, "in", y))
        else:
            for m in metrics:
                completions.append(add_comp(q_spelled, "", m.lower()))
            for d in depts:
                completions.append(add_comp(q_spelled, "in", d))
                
    seen = set()
    unique_completions = []
    for c in completions:
        c_norm = c.lower().strip()
        if c_norm not in seen:
            seen.add(c_norm)
            unique_completions.append(c)
            
    preview = generate_intent_preview(q_spelled, components)
    latency_ms = (time.perf_counter() - start_time) * 1000
    
    return {
        "suggestions": {
            "metrics": [],
            "analysis": unique_completions[:5],
            "comparisons": []
        },
        "preview": preview,
        "latency_ms": latency_ms
    }

@app.post("/api/query")
async def handle_query(payload: QueryBlueprintPayload):
    start_time = time.perf_counter()
    logger.info(f"📥 Received query: '{payload.raw_query}'")
    logger.debug(f"handle_query: incoming payload = {payload}")
    blueprint = payload.blueprint
    
    norm_key = normalize_query_key(payload.raw_query)
    used_semantic_cache = False
    parsed_deterministically = False
    parser_confidence = 0.0
    intent = "unknown"
    top_n_limit = None
    top_n_asc = False
    
    # Try deterministic parser first
    if not blueprint or (not blueprint.metrics and not blueprint.filters and not blueprint.operation):
        # Check for unrecognized/invalid queries (gibberish check)
        correction = get_suggested_correction(payload.raw_query)
        if correction and correction.startswith("Try searching"):
            raise HTTPException(
                status_code=400,
                detail=f"We couldn't recognize any metrics or filters in your query '{payload.raw_query}'. {correction}"
            )

        det_res = parse_query_deterministically(payload.raw_query)
        if det_res and det_res.get("intent") == "invalid_year":
            raise HTTPException(status_code=400, detail=det_res.get("error", "Invalid year in query."))
        if det_res and det_res["confidence"] >= 0.8:
            logger.info(f"⚡ Deterministic Parser Hit! Intent: {det_res['intent']} (Confidence: {det_res['confidence']})")
            blueprint = det_res["blueprint"]
            parsed_deterministically = True
            parser_confidence = det_res["confidence"]
            intent = det_res["intent"]
            top_n_limit = det_res.get("top_n_limit")
            top_n_asc = det_res.get("top_n_asc", False)
            
    # Fallback to Ollama only if the blueprint is completely empty or unparsed
    if not blueprint or (not blueprint.metrics and not blueprint.filters and not blueprint.operation):
        if norm_key in SEMANTIC_CACHE:
            logger.info(f"🧠 Semantic Cache Hit for key: '{norm_key}'")
            blueprint = SEMANTIC_CACHE[norm_key].model_copy()
            used_semantic_cache = True
        else:
            logger.info(f"🤖 Calling Ollama to parse: '{payload.raw_query}'")
            blueprint = await call_ollama_fallback(payload.raw_query)
            logger.info(f"📋 Ollama returned: {blueprint}")
            if blueprint:
                SEMANTIC_CACHE[norm_key] = blueprint.model_copy()
        
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

    # Hallucination check: verify if the parsed metrics are actually mentioned in the raw query text.
    if blueprint.metrics:
        valid_metrics = []
        for m in blueprint.metrics:
            m_clean = m.replace('_', ' ')
            # Check for direct mentions or synonyms
            if m_clean in raw_lower or m.replace('_', '') in raw_lower or any(part in raw_lower for part in m.split('_') if len(part) > 3):
                valid_metrics.append(m)
            elif m == "expenses" and any(w in raw_lower for w in ["expense", "spend", "cost", "spending", "expenses"]):
                valid_metrics.append(m)
            elif m == "operating_cost" and any(w in raw_lower for w in ["operating", "op"]):
                valid_metrics.append(m)
            elif m == "marketing_spend" and "marketing" in raw_lower:
                valid_metrics.append(m)
            elif m == "tax_liability" and "tax" in raw_lower:
                valid_metrics.append(m)
            elif m == "customer_count" and "customer" in raw_lower:
                valid_metrics.append(m)
        blueprint.metrics = valid_metrics

    # 0. Year range validation — reject out-of-range years
    all_years_in_query = re.findall(r'(?<!\d)(\d{4})(?!\d)', raw_lower)
    invalid_years = [y for y in all_years_in_query if not (2020 <= int(y) <= 2026)]
    if invalid_years:
        correction = get_suggested_correction(payload.raw_query)
        err_msg = f"No data available for year(s): {', '.join(invalid_years)}. Available range: 2020-2026."
        if correction:
            err_msg += f" {correction}"
        raise HTTPException(
            status_code=400,
            detail=err_msg
        )

    # 1. Detect compared years (more than one year like 2023, 2024)
    detected_years = extract_detected_years(raw_lower)
    if len(detected_years) > 1:
        blueprint.comparison = {"type": "year", "values": list(dict.fromkeys(detected_years))}
        blueprint.timeframe = {"type": "years", "value": ",".join(list(dict.fromkeys(detected_years)))}
        blueprint.operation = "GRAPH"
    elif len(detected_years) == 1:
        blueprint.timeframe = {"type": "year", "value": detected_years[0]}

    # 2. Detect compared categories
    # Check departments
    detected_depts = []
    for dept in ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"]:
        if dept in raw_lower:
            if dept == "marketing":
                marketing_as_metric_count = (
                    raw_lower.count("marketing spend") + 
                    raw_lower.count("marketing cost") + 
                    raw_lower.count("marketing expense")
                )
                marketing_total_count = raw_lower.count("marketing")
                if marketing_total_count > marketing_as_metric_count:
                    detected_depts.append(dept)
            else:
                detected_depts.append(dept)
    if len(detected_depts) > 1:
        blueprint.comparison = {"type": "department", "values": detected_depts}
        for d in detected_depts:
            if not any(f.get('column') == 'department' and f.get('value') == d for f in blueprint.filters):
                blueprint.filters.append({"column": "department", "value": d})
    elif len(detected_depts) == 1:
        d = detected_depts[0]
        if not any(f.get('column') == 'department' and f.get('value') == d for f in blueprint.filters):
            blueprint.filters.append({"column": "department", "value": d})
        
    # Check regions
    detected_regions = []
    for region in ["north", "south", "east", "west", "central"]:
        if region in raw_lower:
            detected_regions.append(region)
    if len(detected_regions) > 1:
        blueprint.comparison = {"type": "region", "values": detected_regions}
        for r in detected_regions:
            if not any(f.get('column') == 'region' and f.get('value') == r for f in blueprint.filters):
                blueprint.filters.append({"column": "region", "value": r})
    elif len(detected_regions) == 1:
        r = detected_regions[0]
        if not any(f.get('column') == 'region' and f.get('value') == r for f in blueprint.filters):
            blueprint.filters.append({"column": "region", "value": r})

    # Check plants
    detected_plants = []
    for plant in POWER_PLANTS:
        plant_clean = plant.replace('_', ' ')
        if plant in raw_lower or plant_clean in raw_lower:
            detected_plants.append(plant)
    if len(detected_plants) > 1:
        blueprint.comparison = {"type": "plant", "values": detected_plants}
        for p in detected_plants:
            if not any(f.get('column') == 'plant' and f.get('value') == p for f in blueprint.filters):
                blueprint.filters.append({"column": "plant", "value": p})
    elif len(detected_plants) == 1:
        p = detected_plants[0]
        if not any(f.get('column') == 'plant' and f.get('value') == p for f in blueprint.filters):
            blueprint.filters.append({"column": "plant", "value": p})

    # 3. Operation Heuristics
    if "trend" in raw_lower or "over time" in raw_lower or "by year" in raw_lower or "graph" in raw_lower:
        blueprint.operation = "GRAPH"
    elif "breakdown" in raw_lower or "compare" in raw_lower or "by" in raw_lower or any(w in raw_lower for w in ["top plants", "top performing plants", "best plants", "worst plants", "plants breakdown", "compare plants", "plant comparison"]):
        if not blueprint.operation or blueprint.operation.upper() not in ["GRAPH", "TREND"]:
            blueprint.operation = "BREAKDOWN"
            
    # 4. Metric Heuristics
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
        
    if not blueprint.metrics:
        logger.info(f"📊 No metrics specified, defaulting to all core metrics")
        blueprint.metrics = ["revenue", "profit", "expenses", "headcount"]

    # Comparison/Breakdown Dimension Heuristics
    if blueprint.operation in ["BREAKDOWN", "GRAPH"]:
        if not blueprint.comparison or not blueprint.comparison.get('type'):
            if any(w in raw_lower for w in ["by region", "across regions", "compare regions", "compare region", "region comparison", "by regions"]):
                blueprint.comparison = {"type": "region"}
            elif any(w in raw_lower for w in ["by department", "across departments", "compare departments", "compare department", "department comparison", "by dept", "by depts"]):
                blueprint.comparison = {"type": "department"}
            elif any(w in raw_lower for w in ["by plant", "across plants", "compare plants", "compare plant", "plant comparison", "top plants", "top performing plants", "best plants", "worst plants", "plants breakdown"]):
                blueprint.comparison = {"type": "plant"}
                if any(w in raw_lower for w in ["worst", "lowest"]):
                    blueprint.sort_asc = True
                else:
                    blueprint.sort_asc = False
            elif any(w in raw_lower for w in ["by year", "across years", "compare years", "compare year", "year comparison"]):
                blueprint.comparison = {"type": "year"}

    logger.info(f"🔧 Final blueprint - Metrics: {blueprint.metrics}, Filters: {blueprint.filters}, Operation: {blueprint.operation}")
    
    # 2. Result Cache check
    bp_key = blueprint.model_dump_json(exclude_none=True)
    if bp_key in RESULT_CACHE:
        logger.info("⚡ Result Cache Hit!")
        execution_data = RESULT_CACHE[bp_key].copy()
        execution_data["metadata"] = {
            "backend_ms": (time.perf_counter() - start_time) * 1000,
            "cache_hit": True,
            "cache_type": "result",
            "used_semantic_cache": used_semantic_cache,
            "parsed_deterministically": parsed_deterministically,
            "parser_confidence": parser_confidence,
            "intent": intent
        }
        return execution_data

    execution_data = await federated_query_processor(blueprint, payload.raw_query)
    
    if execution_data["status"] == "success":
        num_plants = execution_data.get("plants_queried", len(POWER_PLANTS))
        execution_data["insights"] = {"summary": "Federated query successful.", "analysis": f"Aggregated from {num_plants} sources."}
        
        # Post-Process Top N queries in python
        if parsed_deterministically and intent == "top_n" and execution_data.get("results"):
            results_list = execution_data["results"]
            metric_key = blueprint.metrics[0] if blueprint.metrics else "revenue"
            if results_list and metric_key in results_list[0]:
                # Sort results by metric
                results_sorted = sorted(results_list, key=lambda x: x.get(metric_key, 0) or 0, reverse=not top_n_asc)
                # Limit results
                if top_n_limit:
                    results_sorted = results_sorted[:top_n_limit]
                execution_data["results"] = results_sorted
        
        # Save to Result Cache (only if query succeeded)
        RESULT_CACHE[bp_key] = execution_data.copy()
    
    execution_data["metadata"] = {
        "backend_ms": (time.perf_counter() - start_time) * 1000,
        "cache_hit": False,
        "used_semantic_cache": used_semantic_cache,
        "parsed_deterministically": parsed_deterministically,
        "parser_confidence": parser_confidence,
        "intent": intent
    }
    return execution_data

@app.get("/api/metadata")
def get_metadata():
    registry = MetadataRegistry.get_instance()
    return {"metrics": list(registry.metrics.keys()), "categoricals": {k: list(v["values"]) for k,v in registry.categoricals.items()}}

@app.get("/")
def health(): return {"status": "online"}
