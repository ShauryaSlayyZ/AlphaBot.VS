
import time
import sqlite3
import json
import httpx
import logging
import asyncio
import os
import re
import glob
import threading
from functools import lru_cache
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

# --- Federated Configuration ---
BASE_DIR = os.getenv("ALPHABOT_DB_DIR", os.path.dirname(os.path.abspath(__file__)))
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
    db_files = [f for f in os.listdir(BASE_DIR) if f.endswith('.db') and f not in ['benchmark_test.db', 'corporate_metrics_db_7.db', 'corporate_metrics_db_8.db']]
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


def extract_raw_year_candidates(text: str) -> List[str]:
    import re
    if not text:
        return []
    tokens = re.findall(r'\b[a-zA-Z0-9_-]+\b', text.lower())
    years = []
    for token in tokens:
        matches = re.findall(r'(?<!\d)(\d{4})(?!\d)', token)
        if matches:
            cleaned = re.sub(r'[0-9_fy\-]', '', token)
            if not cleaned:
                years.extend(matches)
    return years


def _make_plurals(word: str) -> List[str]:
    """Generate common plural forms including irregular endings for dimension matching."""
    variants = [word]
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        variants.append(word[:-1] + "ies")   # facility -> facilities
    elif word.endswith(("s", "x", "z", "sh", "ch")):
        variants.append(word + "es")           # status -> statuses
    else:
        variants.append(word + "s")            # vendor -> vendors
    return variants


# --- Semantic Schema Profiler (Dynamic Classification & Profiling Layer) ---
class ColumnProfile(BaseModel):
    classification: str  # METRIC, DIMENSION, IDENTIFIER, STATUS, TIME
    data_type: str
    canonical_concept: Optional[str] = None
    aliases: List[str] = []
    cardinality: Optional[int] = None
    cardinality_ratio: Optional[float] = None
    sample_values: List[Any] = []
    pattern_format: Optional[str] = None
    unit: Optional[str] = None
    aggregation_default: Optional[str] = None

class SchemaProfile(BaseModel):
    database_name: str
    table_name: str
    primary_entity: str = "project"
    columns: Dict[str, ColumnProfile] = {}
    defaults: Dict[str, Any] = {}

class SemanticSchemaProfiler:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.profiles = {}  # db_name -> SchemaProfile
        self._initialized = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def profile_databases(self, registry, force=False):
        if self._initialized and not force:
            return
        logger.info("🔍 Running Semantic Schema Profiler on discovered databases...")
        self.profiles.clear()
        
        # 1. Access dynamic database structures
        for plant in registry.table_names.keys():
            table_name = registry.table_names.get(plant)
            db_path = os.path.join(BASE_DIR, f"{plant}.db")
            if not os.path.exists(db_path) or not table_name:
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                cols = cursor.fetchall()
                
                # Fetch row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cursor.fetchone()[0] or 1
                
                columns_profile = {}
                for col in cols:
                    col_name, col_type = col[1], col[2].upper()
                    col_name_lower = col_name.lower()
                    
                    # Sample distinct values and count cardinality (use subquery limit for cardinality count on large tables)
                    cursor.execute(f"SELECT DISTINCT {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL LIMIT 100")
                    distinct_vals = [row[0] for row in cursor.fetchall()]
                    
                    if row_count > 10000:
                        cursor.execute(f"SELECT COUNT(DISTINCT {col_name}) FROM (SELECT {col_name} FROM {table_name} LIMIT 10000)")
                        sample_cardinality = cursor.fetchone()[0] or 0
                        cardinality_ratio = float(sample_cardinality) / 10000.0
                        cardinality = int(cardinality_ratio * row_count)
                    else:
                        cursor.execute(f"SELECT COUNT(DISTINCT {col_name}) FROM {table_name}")
                        cardinality = cursor.fetchone()[0] or 0
                        cardinality_ratio = float(cardinality) / float(row_count)
                    
                    # Determine classification
                    classification = "DIMENSION"
                    is_numeric = any(t in col_type for t in ["INT", "NUMERIC", "REAL", "DOUBLE", "FLOAT", "DECIMAL"])
                    
                    # Heuristics rules
                    if is_numeric:
                        if re.search(r"(?i)(date|time|year|month|period|quarter|fy_)$", col_name_lower):
                            classification = "TIME"
                        elif col_name_lower in ["project_id", "id", "code"] or re.search(r"(?i)(_id|_code|_uuid|_ref|identifier)$", col_name_lower):
                            classification = "IDENTIFIER"
                        else:
                            classification = "METRIC"
                    else:
                        if re.search(r"(?i)(date|time|year|month|period|quarter|fy_)$", col_name_lower):
                            classification = "TIME"
                        elif re.search(r"(?i)(status|state|stage|phase|payment)$", col_name_lower):
                            classification = "STATUS"
                        elif re.search(r"(?i)(_id|_code|_uuid|_ref|identifier)$", col_name_lower) or (cardinality_ratio > 0.85 and row_count >= 50 and not col_name_lower.endswith("name") and not col_name_lower.endswith("_name")):
                            classification = "IDENTIFIER"
                            
                    # Identify default unit and aggregation defaults
                    unit = None
                    aggregation_default = None
                    if classification == "METRIC":
                        if "percentage" in col_name_lower or "pct" in col_name_lower or "completion" in col_name_lower:
                            unit = "PERCENT"
                            aggregation_default = "AVG"
                        elif "days" in col_name_lower or "delay" in col_name_lower:
                            unit = "DAYS"
                            aggregation_default = "AVG"
                        elif "capacity" in col_name_lower or "mw" in col_name_lower:
                            unit = "MW"
                            aggregation_default = "SUM"
                        else:
                            unit = "USD"
                            aggregation_default = "SUM"
                            
                    # Map to canonical concepts and generate aliases
                    standard_concept_synonyms = {
                        "project_type": ["project_type", "type", "department", "category", "class", "business_unit"],
                        "location": ["location", "region", "site", "territory", "province"],
                        "state": ["state", "province"],
                        "contractor_name": ["contractor_name", "contractor", "vendor_name", "vendor", "partner"],
                        "project_id": ["project_id", "project_code", "project_no", "id", "code"],
                        "fy_year": ["fy_year", "year", "fiscal_year", "period"],
                        "contractor_payment_status": ["payment_status", "contractor_payment", "payment", "contractor_payment_status"],
                        "material_status": ["material_status", "material status", "material_delivery_status"],
                        "budget_allocated": ["budget_allocated", "budget allocated", "allocated budget", "budget"],
                        "budget_used": ["budget_used", "budget used", "used budget", "spent budget", "expenses", "expense", "spending", "spend", "cost", "costs", "operating cost", "operating_cost", "operating_expense", "operating_expenses", "op cost"],
                        "budget_remaining": ["budget_remaining", "budget remaining", "remaining budget", "unspent budget"],
                        "capacity_mw": ["capacity_mw", "capacity", "mw", "power", "power capacity"],
                        "completion_percentage": ["completion_percentage", "completion percentage", "completion", "progress"],
                        "delay_days": ["delay_days", "delay days", "delay", "delays"],
                        "revenue": ["revenue", "profit", "earnings", "income"]
                    }
                    
                    canonical_concept = None
                    aliases = [col_name_lower, col_name_lower.replace('_', ' '), col_name_lower.replace(' ', '_')]
                    for concept, synonyms in standard_concept_synonyms.items():
                        if col_name_lower in synonyms:
                            # Avoid synonym collision: if this column name is not the exact concept name,
                            # but another column matches the concept name exactly in this table, skip mapping.
                            if col_name_lower != concept and concept in [c[1].lower() for c in cols]:
                                continue
                            canonical_concept = concept
                            aliases.extend(synonyms)
                            # Add conversions for synonyms with spaces/underscores
                            for syn in synonyms:
                                aliases.append(syn.replace('_', ' '))
                                aliases.append(syn.replace(' ', '_'))
                            break
                            
                    aliases = sorted(list(set(aliases)))
                    
                    columns_profile[col_name_lower] = ColumnProfile(
                        classification=classification,
                        data_type=col_type,
                        canonical_concept=canonical_concept,
                        aliases=aliases,
                        cardinality=cardinality,
                        cardinality_ratio=cardinality_ratio,
                        sample_values=distinct_vals[:50],
                        unit=unit,
                        aggregation_default=aggregation_default
                    )
                    
                # 4. Generate Defaults
                # KPIs
                metrics_priority = ["revenue", "capacity_mw", "budget_allocated", "budget_used", "budget_remaining", "completion_percentage", "delay_days"]
                metric_cols = [m for m, p in columns_profile.items() if p.classification == "METRIC"]
                sorted_metrics = sorted(metric_cols, key=lambda m: metrics_priority.index(m) if m in metrics_priority else len(metrics_priority))
                kpis = sorted_metrics[:4]
                
                # Groupings
                dim_priority = ["project_type", "location", "state", "contractor_name", "category", "material_status"]
                dim_cols = [d for d, p in columns_profile.items() if p.classification in ["DIMENSION", "STATUS"]]
                sorted_dims = sorted(dim_cols, key=lambda d: dim_priority.index(d) if d in dim_priority else len(dim_priority))
                groupings = sorted_dims[:3]
                
                self.profiles[plant] = SchemaProfile(
                    database_name=plant,
                    table_name=table_name,
                    columns=columns_profile,
                    defaults={
                        "kpi_candidates": kpis,
                        "grouping_dimensions": groupings
                    }
                )
                
                conn.close()
            except Exception as e:
                logger.error(f"Error profiling plant database {plant}: {e}")
                
        self._initialized = True
        logger.info(f"✅ Semantic Schema Profiler initialized successfully with {len(self.profiles)} database profiles.")


# --- Semantic Schema Adapter (Unified Mapping Layer) ---
class SemanticSchemaAdapter:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.column_to_type = {}       # e.g., 'capacity_mw': 'METRIC'
        self.column_to_aliases = {}    # e.g., 'project_type': {'project_type', 'type', 'department', ...}
        self.alias_to_column = {}      # e.g., 'department': 'project_type'
        self.dimensions_values = {}    # e.g., 'project_type': ['Solar', 'Wind', ...]
        self.kpi_candidates = []       # e.g., ['revenue', 'capacity_mw', ...]
        self.grouping_dimensions = []  # e.g., ['project_type', 'location']
        self._initialized = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def build_schema_maps(self, registry):
        logger.info("🔧 Building Dynamic Semantic Schema Map...")
        self.column_to_type.clear()
        self.column_to_aliases.clear()
        self.alias_to_column.clear()
        self.dimensions_values.clear()
        self.kpi_candidates.clear()
        self.grouping_dimensions.clear()

        # Rebuild profiler first
        profiler = SemanticSchemaProfiler.get_instance()
        profiler.profile_databases(registry)

        if not profiler.profiles:
            # Fallback to populating from registry fields (needed for mock test environment)
            for col_name, info in registry.metrics.items():
                self.column_to_type[col_name.lower()] = "METRIC"
                
            for col_name, info in registry.categoricals.items():
                col_lower = col_name.lower()
                self.column_to_type[col_lower] = "DIMENSION"
                self.dimensions_values[col_lower] = list(info.get("values", []))

            # Dynamic classification (Identifier / Status / Date / Metric / Dimension)
            for col_name in list(self.column_to_type.keys()):
                if re.search(r"(?i)(_id|_code|_uuid|identifier|name)$", col_name):
                    self.column_to_type[col_name] = "IDENTIFIER"
                elif re.search(r"(?i)(date|time|year|month|period|quarter|fy_)$", col_name):
                    self.column_to_type[col_name] = "DATE"
                elif re.search(r"(?i)(status|state|stage|phase|payment)$", col_name) and self.column_to_type[col_name] == "DIMENSION":
                    self.column_to_type[col_name] = "STATUS"

            # Standard Concept Mappings & Synonyms
            standard_concept_synonyms = {
                "project_type": ["project_type", "type", "department", "category", "class", "business_unit"],
                "location": ["location", "region", "site", "territory", "province"],
                "state": ["state", "province"],
                "contractor_name": ["contractor_name", "contractor", "vendor_name", "vendor", "partner"],
                "project_id": ["project_id", "project_code", "project_no", "id", "code"],
                "fy_year": ["fy_year", "year", "fiscal_year", "period"],
                "contractor_payment_status": ["payment_status", "contractor_payment", "payment", "contractor_payment_status"],
                "material_status": ["material_status", "material status", "material_delivery_status"],
                "budget_allocated": ["budget_allocated", "budget allocated", "allocated budget", "budget"],
                "budget_used": ["budget_used", "budget used", "used budget", "spent budget", "expenses", "expense", "spending", "spend", "cost", "costs", "operating cost", "operating_cost", "operating_expense", "operating_expenses", "op cost"],
                "budget_remaining": ["budget_remaining", "budget remaining", "remaining budget", "unspent budget"],
                "capacity_mw": ["capacity_mw", "capacity", "mw", "power", "power capacity"],
                "completion_percentage": ["completion_percentage", "completion percentage", "completion", "progress"],
                "delay_days": ["delay_days", "delay days", "delay", "delays"],
                "revenue": ["revenue", "profit", "earnings", "income"]
            }

            # Build alias maps
            for std_key, synonyms in standard_concept_synonyms.items():
                target_col = None
                for col in self.column_to_type:
                    if col in synonyms:
                        target_col = col
                        break
                
                if target_col:
                    self.column_to_aliases[target_col] = set(synonyms)
                    for syn in synonyms:
                        self.alias_to_column[syn] = target_col
                        self.alias_to_column[syn.replace('_', ' ')] = target_col
                        self.alias_to_column[syn.replace(' ', '_')] = target_col

            # Fill in aliases for columns not covered by standard synonyms
            for col_name in self.column_to_type:
                if col_name not in self.column_to_aliases:
                    syns = {col_name, col_name.replace('_', ' '), col_name.replace(' ', '_')}
                    self.column_to_aliases[col_name] = syns
                    for syn in syns:
                        self.alias_to_column[syn] = col_name

            # Generate Defaults
            metrics_priority = ["revenue", "capacity_mw", "budget_allocated", "budget_used", "budget_remaining", "completion_percentage", "delay_days"]
            metric_cols = [m for m in self.column_to_type if self.column_to_type[m] == "METRIC"]
            sorted_metrics = sorted(metric_cols, key=lambda m: metrics_priority.index(m) if m in metrics_priority else len(metrics_priority))
            self.kpi_candidates = sorted_metrics[:4]

            dim_priority = ["project_type", "location", "state", "contractor_name", "category", "material_status"]
            dim_cols = [d for d in self.column_to_type if self.column_to_type[d] in ["DIMENSION", "STATUS"]]
            sorted_dims = sorted(dim_cols, key=lambda d: dim_priority.index(d) if d in dim_priority else len(dim_priority))
            self.grouping_dimensions = sorted_dims[:3]
        else:
            # Merge profiles into unified adapter dictionaries
            for plant, profile in profiler.profiles.items():
                for col_name, col_profile in profile.columns.items():
                    self.column_to_type[col_name] = col_profile.classification
                    if col_profile.classification in ["DIMENSION", "STATUS"] or col_name in registry.categoricals:
                        # Collect dimension values
                        if col_name not in self.dimensions_values:
                            self.dimensions_values[col_name] = []
                        # Merge unique sampled values
                        self.dimensions_values[col_name].extend(col_profile.sample_values)
                        self.dimensions_values[col_name] = sorted(list(set(self.dimensions_values[col_name])))
                    
                    # Merge aliases
                    if col_name not in self.column_to_aliases:
                        self.column_to_aliases[col_name] = set()
                    self.column_to_aliases[col_name].update(col_profile.aliases)
                    
                    for alias in col_profile.aliases:
                        self.alias_to_column[alias] = col_name

                # Merge defaults
                kpis = profile.defaults.get("kpi_candidates", [])
                for kpi in kpis:
                    if kpi not in self.kpi_candidates:
                        self.kpi_candidates.append(kpi)
                
                groupings = profile.defaults.get("grouping_dimensions", [])
                for grp in groupings:
                    if grp not in self.grouping_dimensions:
                        self.grouping_dimensions.append(grp)

            # Limit KPIs and groupings to max size
            self.kpi_candidates = self.kpi_candidates[:4]
            self.grouping_dimensions = self.grouping_dimensions[:3]

        self._initialized = True
        logger.info(f"✅ Semantic Schema Adapter initialized successfully!")
        logger.info(f"   Mapped Columns: {list(self.column_to_type.keys())}")
        logger.info(f"   Default KPIs: {self.kpi_candidates}")
        logger.info(f"   Default Groupings: {self.grouping_dimensions}")

    def resolve_column_name(self, alias_name: str) -> Optional[str]:
        if not alias_name:
            return None
        alias_clean = alias_name.lower().strip()
        if alias_clean in self.column_to_type:
            return alias_clean
        if alias_clean in self.alias_to_column:
            return self.alias_to_column[alias_clean]
        
        for col, aliases in self.column_to_aliases.items():
            for a in aliases:
                a_lower = a.lower()
                # 1. Direct substring match (existing behaviour)
                if alias_clean in a_lower or a_lower in alias_clean:
                    return col
                # 2. Prefix-token match: "supplier" matches "supplier name"
                q_words = alias_clean.split()
                a_words = a_lower.replace('_', ' ').split()
                if q_words and a_words and len(q_words) <= len(a_words):
                    if all(aw.startswith(qw) for qw, aw in zip(q_words, a_words)):
                        return col
        return None

    def get_dimension_values(self, dimension_alias: str) -> List[Any]:
        col = self.resolve_column_name(dimension_alias)
        if col and col in self.dimensions_values:
            return self.dimensions_values[col]
        return []



# --- Metadata Registry (Federated Model) ---
class MetadataRegistry:
    _instance = None
    _lock = threading.Lock()
    _last_checked = 0.0
    _db_mtimes = {}

    def __init__(self):
        self.metrics = {}       # e.g., 'revenue': {'column': 'revenue', 'type': 'NUMERIC'}
        self.categoricals = {}  # e.g., 'department': {'values': ['sales', 'digital', ...]}
        self.table_names = {}   # e.g., 'diablo_canyon': 'metrics_diablo_canyon'
        self._initialized = False

    @classmethod
    def get_instance(cls):
        global POWER_PLANTS
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance.initialize()
                cls._db_mtimes = {}
                for db in POWER_PLANTS:
                    path = os.path.join(BASE_DIR, f"{db}.db")
                    if os.path.exists(path):
                        cls._db_mtimes[db] = os.path.getmtime(path)
            else:
                now = time.time()
                if now - cls._last_checked > 5.0:
                    cls._last_checked = now
                    # Discover power plants
                    try:
                        db_files = [f for f in os.listdir(BASE_DIR) if f.endswith('.db') and f not in ['benchmark_test.db', 'corporate_metrics_db_7.db', 'corporate_metrics_db_8.db']]
                        current_dbs = []
                        for f in db_files:
                            db_name = os.path.splitext(f)[0]
                            if is_plant_db(os.path.join(BASE_DIR, f)):
                                current_dbs.append(db_name)
                        current_dbs = sorted(current_dbs)
                    except Exception:
                        current_dbs = []
                        
                    needs_reload = False
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
                        # Prevent cache corruption after schema reload
                        SEMANTIC_CACHE.clear()
                        RESULT_CACHE.clear()
                        SUGGEST_CACHE.clear()
                        correct_query_spelling.cache_clear()
        return cls._instance

    def initialize(self):
        global POWER_PLANTS
        if self._initialized:
            return
        
        logger.info("🚀 Initializing Singleton Metadata Registry...")
        new_metrics = {}
        new_categoricals = {}
        new_table_names = {}

        # Re-discover plants
        try:
            db_files = [f for f in os.listdir(BASE_DIR) if f.endswith('.db') and f not in ['benchmark_test.db', 'corporate_metrics_db_7.db', 'corporate_metrics_db_8.db']]
            discovered_plants = []
            for f in db_files:
                db_name = os.path.splitext(f)[0]
                if is_plant_db(os.path.join(BASE_DIR, f)):
                    discovered_plants.append(db_name)
            POWER_PLANTS = sorted(discovered_plants)
        except Exception:
            pass

        if not POWER_PLANTS:
            logger.error("FATAL: No database files found.")
            return

        # 1. First discover tables across all databases and save to registry
        for plant in POWER_PLANTS:
            db_path = os.path.join(BASE_DIR, f"{plant}.db")
            if not os.path.exists(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
                res = cursor.fetchone()
                if not res:
                    conn.close()
                    continue
                new_table_names[plant] = res[0]
                conn.close()
            except Exception as e:
                logger.warning(f"Table name discovery error on {plant}: {e}")

        self.table_names = new_table_names
        
        # 2. Run Semantic Schema Profiler on discovered databases (force re-profiling on registry initialization)
        profiler = SemanticSchemaProfiler.get_instance()
        profiler.profile_databases(self, force=True)

        # 3. Populate metrics and categoricals dynamically from profiled metadata
        for plant, profile in profiler.profiles.items():
            db_path = os.path.join(BASE_DIR, f"{plant}.db")
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                for col_name, col_profile in profile.columns.items():
                    classification = col_profile.classification
                    col_type = col_profile.data_type
                    
                    if classification == "METRIC":
                        new_metrics[col_name] = {"column": col_name, "type": col_type}
                    elif classification in ["DIMENSION", "STATUS", "IDENTIFIER"]:
                        if col_name not in new_categoricals:
                            new_categoricals[col_name] = {"values": set()}
                        limit = 100 if classification == "IDENTIFIER" else 50
                        cursor.execute(f"SELECT DISTINCT {col_name} FROM {profile.table_name} WHERE {col_name} IS NOT NULL LIMIT {limit}")
                        new_categoricals[col_name]["values"].update([str(row[0]) for row in cursor.fetchall()])
                    elif classification == "TIME":
                        if col_name not in new_categoricals:
                            new_categoricals[col_name] = {"values": set()}
                        # Limit TIME query to 100 distinct values to avoid fetching thousands of dates
                        cursor.execute(f"SELECT DISTINCT {col_name} FROM {profile.table_name} WHERE {col_name} IS NOT NULL LIMIT 100")
                        for row in cursor.fetchall():
                            val_str = str(row[0])
                            if val_str.isdigit():
                                new_categoricals[col_name]["values"].add(int(val_str))
                            else:
                                new_categoricals[col_name]["values"].add(val_str)
                conn.close()
            except Exception as e:
                logger.warning(f"Dynamic Metadata Extraction Error on {plant}: {e}")

        # Add plant explicitly
        new_categoricals["plant"] = {"values": set(POWER_PLANTS)}

        for k in new_categoricals:
            new_categoricals[k]["values"] = list(new_categoricals[k]["values"])

        self.metrics = new_metrics
        self.categoricals = new_categoricals
        self._initialized = True
        logger.info(f"✅ Singleton Registry Initialized. Metrics: {list(self.metrics.keys())}")
        
        # Build Semantic Maps
        try:
            SemanticSchemaAdapter.get_instance().build_schema_maps(self)
        except Exception as e:
            logger.error(f"Failed to build semantic schema maps: {e}")
            
        try:
            initialize_trie(self)
        except Exception as e:
            logger.warning(f"Failed to initialize suggestions trie: {e}")

# --- Pydantic Models ---
class Blueprint(BaseModel):
    operation: Optional[str] = "SUM"
    metrics: List[str] = []
    filters: List[Dict[str, Any]] = []
    timeframe: Optional[Dict[str, Any]] = None
    timeframes: List[Dict[str, Any]] = []
    is_range: bool = False
    comparison: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None
    sort_asc: Optional[bool] = None
    breakdown_by: Optional[str] = None

class QueryBlueprintPayload(BaseModel):
    raw_query: str
    blueprint: Optional[Blueprint] = None
    force_llm: bool = False
    parsing_metadata: Optional[Dict[str, Any]] = None

# --- Caching Layers ---
SEMANTIC_CACHE = {}  # Normalized Query String -> Blueprint
RESULT_CACHE = {}    # Stable Blueprint JSON String -> Query Response Dict
SUGGEST_CACHE = {}   # Raw query prefix -> suggest response (cleared on registry reload)

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

def initialize_trie(registry=None):
    if registry is None:
        try:
            registry = MetadataRegistry.get_instance()
        except Exception:
            return

    # Clear trie root children to avoid duplicates
    SUGGESTIONS_TRIE.root.children.clear()

    # Dynamic metrics from registry
    for key in registry.metrics.keys():
        name = key.replace('_', ' ').title()
        SUGGESTIONS_TRIE.insert(key, "metric", name)
        for part in key.split('_'):
            if len(part) > 2:
                SUGGESTIONS_TRIE.insert(part, "metric", name)

    # Dynamic categoricals from registry
    for cat_key, cat_info in registry.categoricals.items():
        cat_name = cat_key.replace('_', ' ').title()
        SUGGESTIONS_TRIE.insert(cat_key, cat_key, cat_name)
        for part in cat_key.split('_'):
            if len(part) > 2:
                SUGGESTIONS_TRIE.insert(part, cat_key, cat_name)

        # Insert specific values (limit to prevent memory bloat)
        limit = 100 if cat_key == 'project_id' else 50
        for val in list(cat_info.get("values", []))[:limit]:
            val_str = str(val)
            val_clean = val_str.replace('_', ' ')
            SUGGESTIONS_TRIE.insert(val_str, cat_key, val_clean.title())
            for part in val_str.split('_'):
                if len(part) > 2:
                    SUGGESTIONS_TRIE.insert(part, cat_key, val_clean.title())

def extract_query_components(q: str):
    q_lower = q.lower()
    registry = MetadataRegistry.get_instance()
    
    # 1. Detect metrics dynamically using SemanticSchemaAdapter aliases
    detected_metrics = []
    adapter = SemanticSchemaAdapter.get_instance()
    for key in registry.metrics.keys():
        aliases = adapter.column_to_aliases.get(key, {key})
        for alias in aliases:
            alias_clean = alias.replace('_', ' ').lower()
            if re.search(r'\b' + re.escape(alias_clean) + r'\b', q_lower) or alias_clean in q_lower:
                name = key.replace('_', ' ').title()
                detected_metrics.append((key, name))
                break
            
    # 2. Detect departments/project types (using SemanticSchemaAdapter)
    detected_depts = []
    adapter = SemanticSchemaAdapter.get_instance()
    project_types = adapter.get_dimension_values("project_type")
    for val in project_types:
        val_str = str(val).lower()
        val_clean = val_str.replace('_', ' ')
        if val_str in q_lower or val_clean in q_lower:
            detected_depts.append(str(val))
    # Fallback to legacy departments for compatibility
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
                    if d.capitalize() not in detected_depts:
                        detected_depts.append(d.capitalize())
            else:
                if d.capitalize() not in detected_depts:
                    detected_depts.append(d.capitalize())
            
    # 3. Detect regions/locations (using SemanticSchemaAdapter)
    detected_regions = []
    locations = adapter.get_dimension_values("location")
    for val in locations:
        val_str = str(val).lower()
        val_clean = val_str.replace('_', ' ')
        if val_str in q_lower or val_clean in q_lower:
            detected_regions.append(str(val))
    # Fallback to legacy regions
    all_regions = ["north", "south", "east", "west", "central"]
    for r in all_regions:
        if r in q_lower:
            if r.capitalize() not in detected_regions:
                detected_regions.append(r.capitalize())
            
    # Dynamic detection for other categoricals
    detected_categoricals = {}
    for cat_key, cat_info in registry.categoricals.items():
        if cat_key in ["project_type", "location", "state", "fy_year", "plant"]:
            continue
        detected_categoricals[cat_key] = []
        for val in cat_info.get("values", []):
            val_str = str(val)
            val_clean = val_str.replace('_', ' ').lower()
            val_lower = val_str.lower()
            if re.search(rf'\b{re.escape(val_clean)}\b', q_lower) or re.search(rf'\b{re.escape(val_lower)}\b', q_lower):
                detected_categoricals[cat_key].append(val_str)

    # Fallback to extract any project ID matching pattern that was not in sampled values
    pid_match = re.search(r'\b[a-z]{2,4}-[a-z]{2,4}-\d+\b', q_lower)
    if pid_match:
        matched_pid = pid_match.group(0).upper()
        if "project_id" not in detected_categoricals:
            detected_categoricals["project_id"] = []
        if matched_pid not in detected_categoricals["project_id"]:
            detected_categoricals["project_id"].append(matched_pid)

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
        for cat_list in detected_categoricals.values():
            all_exact_matches.extend([c.lower() for c in cat_list])
        if last_token not in all_exact_matches:
            prefix_results = SUGGESTIONS_TRIE.search_prefix(last_token)
            if prefix_results:
                last_token_match = prefix_results[0]
                
    if last_token_match:
        category = last_token_match["category"]
        name = last_token_match["original_name"]
        if category == "metric" and not any(m[1] == name for m in detected_metrics):
            metric_key = next((k for k in registry.metrics if k == name or k.replace('_', ' ').title() == name), None)
            if metric_key:
                detected_metrics.append((metric_key, name))
        elif category in ["department", "project_type"] and name not in detected_depts:
            detected_depts.append(name)
        elif category in ["region", "location", "state"] and name not in detected_regions:
            detected_regions.append(name)
        elif category == "plant" and name.lower().replace(' ', '_') not in detected_plants:
            plant_key = next((p for p in all_plants if p.replace('_', ' ').title() == name or p == name), None)
            if plant_key:
                detected_plants.append(plant_key)
        elif category in registry.categoricals:
            if category not in detected_categoricals:
                detected_categoricals[category] = []
            if name not in detected_categoricals[category]:
                detected_categoricals[category].append(name)
                
    return {
        "metrics": detected_metrics,
        "departments": detected_depts,
        "regions": detected_regions,
        "plants": detected_plants,
        "years": detected_years,
        "categoricals": detected_categoricals,
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

@lru_cache(maxsize=512)
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
        "revenue", "capacity", "mw", "budget", "allocated", "used", "remaining", "completion", "percentage",
        "delay", "days", "project", "id", "name", "type", "solar", "wind", "hybrid", "location", "state",
        "category", "contractor", "payment", "status", "material", "remarks",
        "diablo", "canyon", "three", "mile", "island", "palo", "verde", "grand", "gulf", "vogtle",
        "hinkley", "point", "kashiwazaki", "darlington",
        # Keep compatibility words for aliases
        "department", "plant", "site", "region", "regions", "dimension", "dimensions", "sales", "digital", "hr", "engineering", "finance", "support", "operations",
        "north", "south", "east", "west", "central"
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
    years = extract_raw_year_candidates(raw_lower)
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
    if not (components["metrics"] or components["departments"] or components["regions"] or components["plants"] or components["years"] or any(components["categoricals"].values()) or has_structural):
        return "Try searching for: 'Revenue Trend', 'Budget Allocated by State', or 'Completion Percentage by Project Type'."
        
    # If spelling was corrected but no year error was found, suggest the spelling correction
    if spelled_query.strip().lower() != raw_query.strip().lower():
        return f"Did you mean: '{spelled_query}'?"
        
    return None

def parse_query_deterministically(raw_query: str) -> Optional[Dict[str, Any]]:
    """Deterministically parses common query patterns to bypass the LLM entirely."""
    raw_lower = raw_query.lower().strip()
    registry = MetadataRegistry.get_instance()
    adapter = SemanticSchemaAdapter.get_instance()
    
    # Exact match for Suggested Business Questions
    if raw_lower in ["top capacity plants", "top revenue plants", "revenue trend", "profit by region", "department performance", "customer growth", "top plants", "top performing plants", "best plants", "worst plants", "budget allocated by state", "completion percentage by project type", "delay days by contractor"]:
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
        elif raw_lower == "top capacity plants":
            intent = "top_n"
            bp.metrics = ["capacity_mw"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "plant"}
            bp.limit = 3
            bp.sort_asc = False
        elif raw_lower in ["top plants", "top performing plants", "best plants", "worst plants"]:
            intent = "top_n"
            bp.metrics = adapter.kpi_candidates or ["revenue", "profit", "expenses", "headcount"]
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
            bp.metrics = ["revenue"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "location"}
        elif raw_lower == "budget allocated by state":
            intent = "breakdown"
            bp.metrics = ["budget_allocated"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "state"}
        elif raw_lower == "completion percentage by project type":
            intent = "breakdown"
            bp.metrics = ["completion_percentage"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "project_type"}
        elif raw_lower == "delay days by contractor":
            intent = "breakdown"
            bp.metrics = ["delay_days"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "contractor_name"}
        elif raw_lower == "department performance":
            intent = "breakdown"
            bp.metrics = ["revenue"]
            bp.operation = "BREAKDOWN"
            bp.comparison = {"type": "project_type"}
        elif raw_lower == "customer growth":
            intent = "trend"
            bp.metrics = ["revenue"]
            bp.operation = "GRAPH"
            
        return {
            "blueprint": bp,
            "intent": intent,
            "confidence": confidence,
            "top_n_limit": bp.limit,
            "top_n_asc": bp.sort_asc
        }
    
    # 1. Identify Metrics (must have at least one metric to parse deterministically, unless querying a project ID)
    detected_metrics = []
    
    # Dynamic metrics match using adapter synonyms/aliases
    for key in registry.metrics.keys():
        aliases = adapter.column_to_aliases.get(key, {key})
        for alias in aliases:
            alias_clean = alias.replace('_', ' ').lower()
            if re.search(r'\b' + re.escape(alias_clean) + r'\b', raw_lower):
                if key not in detected_metrics:
                    detected_metrics.append(key)
                break
            
    # Check if a project ID is mentioned (either in registry or pattern PRJ-[A-Z]{3}-\d+)
    has_project_id = False
    project_id_values = registry.categoricals.get("project_id", {}).get("values", [])
    for pid in project_id_values:
        pid_lower = str(pid).lower()
        if pid_lower in raw_lower:
            has_project_id = True
            break
    if not has_project_id:
        # Broadened: matches REF-001, WH-123, AST-A1, PRJ-DAR-001, etc.
        if re.search(r'\b[a-z0-9]{2,6}-[a-z0-9]{1,6}(-[a-z0-9]+)?\b', raw_lower):
            has_project_id = True
            
    if not detected_metrics and not has_project_id:
        return None
        
    bp = Blueprint()
    bp.metrics = detected_metrics
    
    # 2. Extract Year context — only 2020-2026 are valid data years
    all_years_in_query = extract_raw_year_candidates(raw_lower)
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
    dynamic_filters = []
    for cat_key, cat_info in registry.categoricals.items():
        if cat_key in ["fy_year", "plant"]:
            continue
        for val in cat_info.get("values", []):
            val_str = str(val)
            val_clean = val_str.replace('_', ' ').lower()
            val_lower = val_str.lower()
            if re.search(rf'\b{re.escape(val_clean)}\b', raw_lower) or re.search(rf'\b{re.escape(val_lower)}\b', raw_lower):
                col_name = cat_key
                if not any(f["column"] == col_name and f["value"] == val_str for f in dynamic_filters):
                    dynamic_filters.append({"column": col_name, "value": val_str})
                    
    # Fallback to extract any project ID matching pattern that was not in sampled values
    # Broadened: matches REF-001, WH-123, AST-A1, PRJ-DAR-001, etc.
    pid_match = re.search(r'\b[a-z0-9]{2,6}-[a-z0-9]{1,6}(-[a-z0-9]+)?\b', raw_lower)
    if pid_match:
        matched_pid = pid_match.group(0).upper()
        # Dynamically resolve the IDENTIFIER column name from the adapter
        # Look if the query contains words matching aliases of any IDENTIFIER or DIMENSION column first!
        _identifier_col = None
        for col_name, col_type in adapter.column_to_type.items():
            if col_type in ["IDENTIFIER", "DIMENSION"]:
                aliases = adapter.column_to_aliases.get(col_name, {col_name})
                for alias in aliases:
                    alias_clean = alias.replace('_', ' ').lower()
                    if alias_clean in ["id", "code", "type"] and alias_clean != col_name:
                        continue
                    if re.search(r'\b' + re.escape(alias_clean) + r'\b', raw_lower):
                        _identifier_col = col_name
                        break
            if _identifier_col:
                break
        
        # If no specific IDENTIFIER column matched, fallback to the first IDENTIFIER column
        if not _identifier_col:
            _identifier_col = next(
                (col for col, t in adapter.column_to_type.items() if t == "IDENTIFIER"),
                "project_id"
            )
        if not any(f["value"].upper() == matched_pid for f in dynamic_filters):
            dynamic_filters.append({"column": _identifier_col, "value": matched_pid})

    # Legacy fallbacks
    for dept in ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"]:
        if re.search(rf'\b{dept}\b', raw_lower):
            target_col = adapter.resolve_column_name("project_type") or "project_type"
            if not any(f["column"] == target_col and f["value"].lower() == dept for f in dynamic_filters):
                if dept == "marketing":
                    marketing_as_metric_count = (
                        raw_lower.count("marketing spend") + 
                        raw_lower.count("marketing cost") + 
                        raw_lower.count("marketing expense")
                    )
                    marketing_total_count = len(re.findall(r'\bmarketing\b', raw_lower))
                    if marketing_total_count > marketing_as_metric_count:
                        dynamic_filters.append({"column": target_col, "value": dept.capitalize()})
                else:
                    dynamic_filters.append({"column": target_col, "value": dept.capitalize()})

    for region in ["north", "south", "east", "west", "central"]:
        if re.search(rf'\b{region}\b', raw_lower):
            target_col = adapter.resolve_column_name("location") or "location"
            if not any(f["column"] == target_col and f["value"].lower() == region for f in dynamic_filters):
                dynamic_filters.append({"column": target_col, "value": region.capitalize()})

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
    from collections import Counter
    col_counts = Counter(f["column"] for f in dynamic_filters)
    has_multiple_values_for_col = any(count > 1 for count in col_counts.values())
    
    is_compare_query = any(w in raw_lower for w in ["compare", "comparison", "versus", "vs", "between"])
    if is_compare_query or len(detected_years) > 1 or has_multiple_values_for_col or len(detected_plants) > 1:
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
    bp.filters = dynamic_filters
    for p in detected_plants:
        bp.filters.append({"column": "plant", "value": p})

    # Comparison details populating
    if intent == "comparison":
        bp.operation = "GRAPH" if (len(detected_years) > 1 or is_trend_query) else "BREAKDOWN"
        if len(detected_years) > 1:
            bp.comparison = {"type": "year", "values": list(dict.fromkeys(detected_years))}
        elif len(detected_plants) > 1:
            bp.comparison = {"type": "plant", "values": detected_plants}
        else:
            comp_set = False
            for col, count in col_counts.items():
                if count > 1:
                    bp.comparison = {"type": col, "values": [f["value"] for f in dynamic_filters if f["column"] == col]}
                    comp_set = True
                    break
            if not comp_set:
                dimension = None
                for cat_key in registry.categoricals.keys():
                    aliases = adapter.column_to_aliases.get(cat_key, {cat_key})
                    matched = False
                    for alias in aliases:
                        alias_clean = alias.replace('_', ' ').lower()
                        # Generate full-alias plurals AND word-part plurals (e.g., "facilities" from "facility name")
                        candidates = list(_make_plurals(alias_clean))
                        for word in alias_clean.split():
                            if len(word) > 3:
                                candidates.extend(_make_plurals(word))
                        matched = False
                        for var in candidates:
                            if any(w in raw_lower for w in [f"by {var}", f"across {var}", f"compare {var}", f"{var} comparison", f"split by {var}"]):
                                dimension = cat_key
                                matched = True
                                break
                        if matched:
                            break
                    if matched:
                        break
                        
                if not dimension:
                    if any(w in raw_lower for w in ["by year", "across years", "compare years", "compare year", "year comparison"]):
                        dimension = "year"
                        
                if dimension:
                    bp.comparison = {"type": dimension}
                else:
                    confidence = 0.7
            
    # Top N / Breakdown details populating
    top_n_limit = None
    top_n_asc = False
    if intent == "top_n":
        bp.operation = "BREAKDOWN"
        dimension = None
        for cat_key in registry.categoricals.keys():
            aliases = adapter.column_to_aliases.get(cat_key, {cat_key})
            for alias in aliases:
                alias_clean = alias.replace('_', ' ').lower()
                # Generate full-alias plurals AND word-part plurals
                candidates = list(_make_plurals(alias_clean))
                for word in alias_clean.split():
                    if len(word) > 3:
                        candidates.extend(_make_plurals(word))
                matched = False
                for var in candidates:
                    if re.search(rf'\b(top|best|highest|lowest|worst|max|min)\s+(\d+\s+)?{re.escape(var)}\b', raw_lower) or any(w in raw_lower for w in [f"top {var}", f"best {var}", f"worst {var}"]):
                        dimension = cat_key
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
                
        if not dimension:
            if "plant" in raw_lower:
                dimension = "plant"
            elif any(w in raw_lower for w in ["department", "dept", "project type", "project_type"]):
                dimension = "project_type" if "project_type" in registry.categoricals else "department"
            elif any(w in raw_lower for w in ["region", "state"]):
                dimension = "state" if "state" in registry.categoricals else "region"
            else:
                dimension = "project_type" if "project_type" in registry.categoricals else "department"
            
        bp.comparison = {"type": dimension}
        
        limit_match = re.search(r'\b(top|best|highest|lowest|worst)\s+(\d+)\b', raw_lower)
        if limit_match:
            top_n_limit = int(limit_match.group(2))
        else:
            top_n_limit = 3  # default
            
        if any(w in raw_lower for w in ["lowest", "worst", "min"]):
            top_n_asc = True
            
        bp.limit = top_n_limit
        bp.sort_asc = top_n_asc
            
    elif intent == "trend":
        bp.operation = "GRAPH"
        
    elif intent == "breakdown":
        bp.operation = "BREAKDOWN"
        dimension = None
        for cat_key in registry.categoricals.keys():
            aliases = adapter.column_to_aliases.get(cat_key, {cat_key})
            matched = False
            for alias in aliases:
                alias_clean = alias.replace('_', ' ').lower()
                # Generate full-alias plurals AND word-part plurals
                candidates = list(_make_plurals(alias_clean))
                for word in alias_clean.split():
                    if len(word) > 3:
                        candidates.extend(_make_plurals(word))
                matched = False
                for var in candidates:
                    if f"by {var}" in raw_lower or f"split by {var}" in raw_lower or f"divided by {var}" in raw_lower or var in raw_lower:
                        dimension = cat_key
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
                
        if not dimension:
            if "by year" in raw_lower or "year" in raw_lower:
                dimension = "year"
                
        if dimension == "year":
            bp.operation = "GRAPH"
        elif dimension:
            bp.comparison = {"type": dimension}
        else:
            has_project_type_filter = any(f["column"] in ["project_type", "department"] for f in dynamic_filters)
            has_location_filter = any(f["column"] in ["location", "state", "region"] for f in dynamic_filters)
            if has_project_type_filter and not has_location_filter:
                bp.comparison = {"type": "state" if "state" in registry.categoricals else "region"}
            else:
                bp.comparison = {"type": "project_type" if "project_type" in registry.categoricals else "department"}
                
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
    
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    if table_name not in registry.table_names.values():
        raise ValueError(f"Unauthorized table name: {table_name}")

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

def get_time_column_for_db(plant: str, fallback: str = "record_date") -> str:
    """Return the TIME-classified column name for a given database, or fallback."""
    profiler = SemanticSchemaProfiler.get_instance()
    profile = profiler.profiles.get(plant)
    if profile:
        for col_name, col_prof in profile.columns.items():
            if col_prof.classification == "TIME":
                return col_name
    return fallback

def build_federated_query_parts(bp: Blueprint, time_col: str = "record_date") -> (str, List[str], tuple, str, str, str):
    registry = MetadataRegistry.get_instance()
    
    # Resolve metrics through SemanticSchemaAdapter
    resolved_metrics = []
    for m in bp.metrics:
        resolved_m = SemanticSchemaAdapter.get_instance().resolve_column_name(m)
        if resolved_m:
            resolved_metrics.append(resolved_m)
        else:
            resolved_metrics.append(m)
    bp.metrics = resolved_metrics

    valid_metrics = list(registry.metrics.keys())
    valid_dims = list(registry.categoricals.keys())
    
    # Whitelist of allowed column names to prevent SQL Injection
    allowed_cols = set(valid_metrics + valid_dims + ["plant", "year", "fy_year", "record_date", "comparison_group", "label", "state"])
    
    # Reject unknown metrics
    for m in bp.metrics:
        if m not in valid_metrics:
            raise ValueError(f"Invalid or unauthorized metric requested: {m}")
            
    # Group filters by column name
    from collections import defaultdict
    grouped_filters = defaultdict(list)
    for f in bp.filters:
        col = f.get('column')
        val = f.get('value')
        if not col or val is None:
            continue
            
        col_lower = col.lower()
        if col_lower == "plant":
            continue
        target = SemanticSchemaAdapter.get_instance().resolve_column_name(col_lower)
            
        if not target or target not in allowed_cols:
            raise ValueError(f"Invalid or unauthorized filter column: {col}")
            
        if target in registry.categoricals:
            matching_val = next((v for v in registry.categoricals[target]['values'] if str(v).lower() == str(val).lower() or str(v).lower().replace(' ', '_') == str(val).lower()), None)
            if matching_val:
                grouped_filters[target].append(matching_val)
            else:
                grouped_filters[target].append(val)
        else:
            grouped_filters[target].append(val)
            
    where_clauses, params = [], []
    for col, values in grouped_filters.items():
        if col == 'plant':
            continue
        if col not in allowed_cols:
            raise ValueError(f"Invalid or unauthorized filter column: {col}")
        unique_vals = list(dict.fromkeys(values))
        if len(unique_vals) == 1:
            where_clauses.append(f"{col} = ?")
            params.append(unique_vals[0])
        else:
            placeholders = ", ".join("?" for _ in unique_vals)
            where_clauses.append(f"{col} IN ({placeholders})")
            params.extend(unique_vals)

    # 2. Numeric Comparisons (e.g., delay < 25)
    if bp.comparison and not bp.comparison.get('type'):
        comp = bp.comparison
        c_metric = comp.get('metric')
        c_op = comp.get('operator')
        c_val = comp.get('value')
        if c_metric:
            if c_metric not in valid_metrics:
                raise ValueError(f"Invalid or unauthorized comparison metric: {c_metric}")
            if c_op not in ['<', '>', '=', '<=', '>=']:
                raise ValueError(f"Invalid comparison operator: {c_op}")
            where_clauses.append(f"{c_metric} {c_op} ?")
            params.append(c_val)

    # Timeframe handling
    is_year_comparison = False
    comparison_years = []
    tfs = bp.timeframes or []
    if bp.timeframe and bp.timeframe.get('value'):
        if not any(tf.get('value') == bp.timeframe.get('value') for tf in tfs):
            tfs = [bp.timeframe] + tfs
        
    dates_val = []
    years_val = []
    for tf in tfs:
        val_str = str(tf.get('value', '')).replace("FY", "").strip()
        if tf.get('type') == 'date' or re.match(r'^\d{4}-\d{2}-\d{2}$', val_str):
            dates_val.append(val_str[:10])
        elif tf.get('type') == 'years':
            years_val.extend(val_str.split(","))
        else:
            years_val.append(val_str)
            
    for d in dates_val:
        where_clauses.append(f"{time_col} BETWEEN ? AND ?")
        params.extend([f"{d} 00:00:00", f"{d} 23:59:59"])
        
    if years_val:
        is_new_schema = "fy_year" in registry.categoricals or "project_type" in registry.categoricals or "location" in registry.categoricals or "project_id" in registry.categoricals
        if is_new_schema:
            years_parsed = [int(y) if str(y).isdigit() else y for y in years_val]
            if len(years_parsed) == 1:
                where_clauses.append("fy_year = ?")
                params.append(years_parsed[0])
            else:
                placeholders = ", ".join("?" for _ in years_parsed)
                where_clauses.append(f"fy_year IN ({placeholders})")
                params.extend(years_parsed)
        else:
            if len(years_val) == 1:
                where_clauses.append(f"strftime('%Y', {time_col}) = ?")
                params.append(str(years_val[0]))
            else:
                placeholders = ", ".join("?" for _ in years_val)
                where_clauses.append(f"strftime('%Y', {time_col}) IN ({placeholders})")
                params.extend(str(y) for y in years_val)

    metric_cols = [m for m in bp.metrics if m in registry.metrics]
    # Fix C: dynamic IDENTIFIER detection instead of hardcoded 'project_id'
    _profiler = SemanticSchemaProfiler.get_instance()
    def _is_identifier_col(col_name: str) -> bool:
        for _profile in _profiler.profiles.values():
            _cp = _profile.columns.get(col_name)
            if _cp and _cp.classification == "IDENTIFIER":
                return True
        return False
    is_profile_request = any(_is_identifier_col(col) for col in grouped_filters)
    
    if not metric_cols and not is_profile_request:
        metric_cols = ["revenue"] if "revenue" in registry.metrics else [list(registry.metrics.keys())[0]]

    # Handle grouping / graphing
    sql_select = ""
    sql_group_by = ""
    sql_order_by = ""
    
    if is_profile_request:
        if metric_cols:
            # Dynamic: find the IDENTIFIER column name instead of hardcoding 'project_id'
            _id_col = next(
                (col for col in grouped_filters if _is_identifier_col(col)),
                "project_id"
            )
            select_cols = [_id_col, time_col] + metric_cols
            sql_select_final = ", ".join(select_cols)
        else:
            sql_select_final = "*"
        where_str = " AND ".join(where_clauses)
        return where_str, metric_cols, tuple(params), sql_select_final, sql_group_by, sql_order_by

    op = bp.operation.upper() if bp.operation else "SUM"
    
    grouping_dimension = None
    if bp.breakdown_by:
        bby = bp.breakdown_by.lower().strip()
        if bby == "plant":
            grouping_dimension = "plant"
        else:
            grouping_dimension = SemanticSchemaAdapter.get_instance().resolve_column_name(bby)
            if not grouping_dimension:
                raise ValueError(f"Invalid or unauthorized breakdown column: {bp.breakdown_by}")
            
    elif bp.comparison and bp.comparison.get('type'):
        comp_type = bp.comparison['type']
        if comp_type == "plant":
            grouping_dimension = "plant"
        elif comp_type == "year":
            grouping_dimension = "year"
        else:
            grouping_dimension = SemanticSchemaAdapter.get_instance().resolve_column_name(comp_type)
            if not grouping_dimension:
                raise ValueError(f"Invalid or unauthorized comparison dimension: {comp_type}")

    # Helper: detect if time_col stores an integer/text year vs a date/timestamp string
    def _tc_is_numeric() -> bool:
        for profile in SemanticSchemaProfiler.get_instance().profiles.values():
            cp = profile.columns.get(time_col)
            if cp:
                if any(t in cp.data_type.upper() for t in ["INT", "NUMERIC", "REAL", "DOUBLE", "FLOAT"]):
                    return True
                if cp.sample_values:
                    all_years_or_no_hyphen = True
                    for val in cp.sample_values:
                        val_str = str(val).strip()
                        if '-' in val_str or '/' in val_str:
                            all_years_or_no_hyphen = False
                            break
                    if all_years_or_no_hyphen:
                        return True
        return False
    _time_col_numeric = _tc_is_numeric()

    if op in ["GRAPH", "TREND"]:
        if grouping_dimension:
            comp_type = grouping_dimension
            if comp_type == 'year':
                if _time_col_numeric:
                    sql_select = f"{time_col}, strftime('%Y', date('now')) as comparison_group"
                    sql_group_by = f"GROUP BY {time_col}"
                else:
                    sql_select = f"strftime('%m', {time_col}) as {time_col}, strftime('%Y', {time_col}) as comparison_group"
                    sql_group_by = f"GROUP BY strftime('%m', {time_col}), strftime('%Y', {time_col})"
                sql_order_by = f"ORDER BY {time_col} ASC, comparison_group ASC"
            elif comp_type == 'plant':
                group_by_month = bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']
                if _time_col_numeric:
                    sql_select = f"{time_col}"
                    sql_group_by = f"GROUP BY {time_col}"
                elif group_by_month:
                    sql_select = f"strftime('%Y-%m', {time_col}) as {time_col}"
                    sql_group_by = f"GROUP BY strftime('%Y-%m', {time_col})"
                else:
                    sql_select = f"strftime('%Y', {time_col}) as {time_col}"
                    sql_group_by = f"GROUP BY strftime('%Y', {time_col})"
                sql_order_by = f"ORDER BY {time_col} ASC"
            else:
                if comp_type not in allowed_cols:
                    raise ValueError(f"Invalid grouping dimension: {comp_type}")
                comp_col = comp_type
                group_by_month = bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']
                if _time_col_numeric:
                    sql_select = f"{time_col}, {comp_col} as comparison_group"
                    sql_group_by = f"GROUP BY {time_col}, {comp_col}"
                elif group_by_month:
                    sql_select = f"strftime('%Y-%m', {time_col}) as {time_col}, {comp_col} as comparison_group"
                    sql_group_by = f"GROUP BY strftime('%Y-%m', {time_col}), {comp_col}"
                else:
                    sql_select = f"strftime('%Y', {time_col}) as {time_col}, {comp_col} as comparison_group"
                    sql_group_by = f"GROUP BY strftime('%Y', {time_col}), {comp_col}"
                sql_order_by = f"ORDER BY {time_col} ASC, comparison_group ASC"
        else:
            if _time_col_numeric:
                sql_select = f"{time_col}"
                sql_group_by = f"GROUP BY {time_col}"
            elif bp.timeframe and bp.timeframe.get('type') in ['year', 'monthly']:
                sql_select = f"strftime('%Y-%m', {time_col}) as {time_col}"
                sql_group_by = f"GROUP BY strftime('%Y-%m', {time_col})"
            else:
                sql_select = f"strftime('%Y', {time_col}) as {time_col}"
                sql_group_by = f"GROUP BY strftime('%Y', {time_col})"
            sql_order_by = f"ORDER BY {time_col} ASC"

    elif op == "BREAKDOWN":
        if grouping_dimension and grouping_dimension != 'year':
            comp_col = grouping_dimension
            if comp_col == 'plant':
                sql_select = ""
                sql_group_by = ""
                sql_order_by = ""
            else:
                if comp_col not in allowed_cols:
                    raise ValueError(f"Invalid breakdown dimension: {comp_col}")
                sql_select = f"{comp_col} as {comp_col}"
                sql_group_by = f"GROUP BY {comp_col}"
                sql_order_by = f"ORDER BY 1 ASC"
        else:
            if "department" in valid_dims or "region" in valid_dims:
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
            else:
                group_col_name = "project_type" if "project_type" in valid_dims else "location"
                if group_col_name not in allowed_cols:
                    raise ValueError(f"Invalid default breakdown dimension: {group_col_name}")
                sql_select = f"{group_col_name} as {group_col_name}"
                sql_group_by = f"GROUP BY {group_col_name}"
            sql_order_by = "ORDER BY 1 ASC"
        
    select_parts = []
    if sql_select:
        select_parts.append(sql_select)
    for m in metric_cols:
        is_rate_col = any(keyword in m.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
        if op in ["MIN", "MAX"]:
            select_parts.append(f"{op}({m}) as {m}")
        elif is_rate_col:
            select_parts.append(f"AVG({m}) as {m}")
        else:
            select_parts.append(f"SUM({m}) as {m}")
        
    sql_select_final = ", ".join(select_parts)
    where_str = " AND ".join(where_clauses)
    return where_str, metric_cols, tuple(params), sql_select_final, sql_group_by, sql_order_by

async def federated_query_processor(bp: Blueprint, raw_query: str, parsing_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Queries databases in parallel (or specifically) and aggregates results."""
    registry = MetadataRegistry.get_instance()
    
    # 0. Timeframe Boundary Guard
    tf_list = bp.timeframes or ([bp.timeframe] if bp.timeframe else [])
    if tf_list:
        allowed_years = set(registry.categoricals.get('fy_year', {}).get('values', []))
        if allowed_years:
            for tf in tf_list:
                val_str = str(tf.get('value', '')).replace("FY", "").strip()
                if val_str.isdigit():
                    y_int = int(val_str)
                    if y_int not in allowed_years:
                        logger.warning(f"⚠️ Validation Blocked: Year {y_int} is out of database bounds.")
                        return {
                            "status": "error",
                            "message": f"Ambiguity or error: The requested year {y_int} is outside the available database bounds ({min(allowed_years)} - {max(allowed_years)}).",
                            "results": []
                        }

    # 1. Zero-Trust Dynamic Entity Validation & Fuzzy Recovery
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
                
            # Perform Fuzzy Match
            found_match = None
            for c_lower, c_orig in candidate_map.items():
                dist = get_levenshtein_distance(u, c_lower)
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

    # 2. Re-run building query parts after potential fuzzy recovery changes
    # Resolve time column dynamically — single-plant queries use per-DB TIME column
    _target_plants_for_time = [f['value'] for f in bp.filters if f.get('column') == 'plant']
    _time_col = get_time_column_for_db(_target_plants_for_time[0]) if len(_target_plants_for_time) == 1 else "record_date"
    where_str_part, metric_cols, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp, time_col=_time_col)
    metric_key = metric_cols[0] if metric_cols else None
    
    sql_where = f"WHERE {where_str_part}" if where_str_part else ""

    # Determine which plants to query (support multiple plants routing)
    target_plants = [f['value'] for f in bp.filters if f.get('column') == 'plant']
    plants_to_query = [p for p in target_plants if p in POWER_PLANTS]
    if not plants_to_query:
        # Check if project_id prefix can route to a specific plant
        project_ids = [f['value'] for f in bp.filters if f.get('column') == 'project_id']
        if project_ids:
            routed_plant = None
            pid_upper = str(project_ids[0]).upper()
            prefix_map = {
                "PRJ-DAR": "darlington",
                "PRJ-DIA": "diablo_canyon",
                "PRJ-GRA": "grand_gulf",
                "PRJ-HIN": "hinkley_point",
                "PRJ-KAS": "kashiwazaki",
                "PRJ-PAL": "palo_verde",
                "PRJ-THR": "three_mile_island",
                "PRJ-VOG": "vogtle"
            }
            for pref, plant in prefix_map.items():
                if pid_upper.startswith(pref):
                    routed_plant = plant
                    break
            if routed_plant and routed_plant in POWER_PLANTS:
                plants_to_query = [routed_plant]
                logger.info(f"🔮 Routed project_id '{pid_upper}' specifically to plant '{routed_plant}'")

    if not plants_to_query:
        plants_to_query = POWER_PLANTS

    # Fix A: Column-aware pre-flight routing — skip DBs missing requested columns
    _profiler_fqp = SemanticSchemaProfiler.get_instance()
    _requested_cols = set(metric_cols)
    for _f in bp.filters:
        _fc = _f.get('column')
        if _fc and _fc not in ('plant', None):
            _requested_cols.add(_fc)
    if _requested_cols:
        _capable = [
            p for p in plants_to_query
            if _profiler_fqp.profiles.get(p) is None
            or _requested_cols.issubset(_profiler_fqp.profiles[p].columns.keys())
        ]
        if _capable:
            plants_to_query = _capable
            logger.info(f"🔀 Column-aware routing: restricted to {plants_to_query}")

    # Resolve time_col now that plants_to_query is finalized
    if len(plants_to_query) == 1:
        _time_col = get_time_column_for_db(plants_to_query[0])
        # Rebuild query parts with correct time column if it changed
        if _time_col != "record_date":
            where_str_part, metric_cols, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp, time_col=_time_col)
            sql_where = f"WHERE {where_str_part}" if where_str_part else ""

    op = bp.operation.upper() if bp.operation else "SUM"

    # Fix C: Dynamic profile detection — check IDENTIFIER classification instead of hardcoded 'project_id'
    is_profile_request = any(
        any(
            _profiler_fqp.profiles.get(p) and
            _profiler_fqp.profiles[p].columns.get(f.get('column', '')) and
            _profiler_fqp.profiles[p].columns[f.get('column', '')].classification == "IDENTIFIER"
            for p in plants_to_query
        )
        for f in bp.filters if f.get('column') not in (None, 'plant')
    )
    
    # Construct query string
    if is_profile_request:
        sql_to_run = f"SELECT {sql_select} FROM {{table_name}} {sql_where} {sql_order_by}".strip()
    else:
        query_parts = [f"SELECT {sql_select} FROM {{table_name}}", sql_where]
        if sql_group_by:
            query_parts.append(sql_group_by)
        if sql_order_by:
            query_parts.append(sql_order_by)
        sql_to_run = " ".join(part for part in query_parts if part)

    # --- Dynamic Contextual KPI Query ---
    kpi_candidates = ["revenue", "capacity_mw", "budget_allocated", "budget_used"]
    existing_kpis = [c for c in kpi_candidates if c in registry.metrics]
    
    default_metrics = set(kpi_candidates)
    dynamic_metric = None
    for m in bp.metrics:
        if m not in default_metrics:
            dynamic_metric = m
            break
            
    if dynamic_metric and dynamic_metric in registry.metrics and dynamic_metric not in existing_kpis:
        existing_kpis.append(dynamic_metric)
        
    kpi_select_parts = []
    for col in existing_kpis:
        is_rate_col = any(keyword in col.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
        if is_rate_col:
            kpi_select_parts.append(f"AVG({col}) as {col}")
        else:
            kpi_select_parts.append(f"SUM({col}) as {col}")
            
    if kpi_select_parts and not is_profile_request:
        kpi_sql_select = ", ".join(kpi_select_parts)
        kpi_sql_to_run = f"SELECT {kpi_sql_select} FROM {{table_name}} {sql_where}".strip()
    else:
        kpi_sql_to_run = None

    # Run queries in parallel
    tasks = [run_query_on_single_db(plant, sql_to_run, params) for plant in plants_to_query]
    if kpi_sql_to_run:
        kpi_tasks = [run_query_on_single_db(plant, kpi_sql_to_run, params) for plant in plants_to_query]
    else:
        kpi_tasks = []
    
    # Gather both sets of tasks
    all_results = await asyncio.gather(*(tasks + kpi_tasks))
    results_per_db = all_results[:len(tasks)]
    kpi_results_per_db = all_results[len(tasks):] if kpi_sql_to_run else []

    # Aggregation / Full Result Processing for Project Profiles
    if is_profile_request:
        results = []
        for res in results_per_db:
            results.extend(res)
        return {
            "status": "success",
            "results": results,
            "sql_query": sql_to_run.replace("{table_name}", "metrics_site_X"),
            "unit": "RawData",
            "plants_queried": len(plants_to_query)
        }

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
            counts_map = {} # (rec_date, comp_group, metric) -> count
            for res_list in results_per_db:
                for row in res_list:
                    rec_date = row.get('record_date')
                    comp_group = row.get('comparison_group')
                    if rec_date is None or comp_group is None:
                        continue
                    
                    if rec_date not in aggregated_map:
                        aggregated_map[rec_date] = {}
                        counts_map[rec_date] = {}
                    if comp_group not in aggregated_map[rec_date]:
                        aggregated_map[rec_date][comp_group] = {m: 0.0 for m in metric_cols}
                        counts_map[rec_date][comp_group] = {m: 0 for m in metric_cols}
                        
                    for m in metric_cols:
                        val = row.get(m)
                        if val is not None:
                            aggregated_map[rec_date][comp_group][m] += val
                            counts_map[rec_date][comp_group][m] += 1
                            
            results = []
            for rec_date, comp_dict in sorted(aggregated_map.items()):
                row_data = {"record_date": rec_date}
                for comp_group, metrics_dict in comp_dict.items():
                    def get_val(m):
                        is_rate_col = any(keyword in m.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
                        v = metrics_dict[m]
                        c = counts_map[rec_date][comp_group][m]
                        if is_rate_col and c > 0:
                            return round(v / c, 2)
                        return round(v, 2)

                    if len(metric_cols) == 1:
                        row_data[str(comp_group)] = get_val(metric_cols[0])
                    else:
                        for m in metric_cols:
                            row_data[f"{comp_group}_{m}"] = get_val(m)
                results.append(row_data)
        else:
            # Standard aggregation across databases
            aggregated_map = {}
            group_key_col = None
            counts_map = {} # (group_val, metric) -> count
            for res_list in results_per_db:
                for row in res_list:
                    current_group_key_col = next((k for k, v in row.items() if isinstance(v, str)), None)
                    if not current_group_key_col:
                        continue
                    group_key_col = current_group_key_col
                    group_val = row[group_key_col]
                    
                    if group_val not in aggregated_map:
                        aggregated_map[group_val] = {m: 0.0 for m in metric_cols}
                        counts_map[group_val] = {m: 0 for m in metric_cols}
                    
                    for m in metric_cols:
                        metric_val = row.get(m)
                        if metric_val is not None:
                            aggregated_map[group_val][m] += metric_val
                            counts_map[group_val][m] += 1
                            
            if group_key_col:
                results = []
                for k, metrics_dict in sorted(aggregated_map.items()):
                    row = {group_key_col: k}
                    for m in metric_cols:
                        is_rate_col = any(keyword in m.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
                        if is_rate_col and counts_map[k][m] > 0:
                            row[m] = round(metrics_dict[k][m] if isinstance(metrics_dict, dict) and k in metrics_dict and isinstance(metrics_dict[k], dict) and m in metrics_dict[k] else metrics_dict[m] / counts_map[k][m], 2)
                        else:
                            row[m] = round(metrics_dict[m], 2)
                    results.append(row)
            else:
                results = []

        # Sequential growth calculations
        if ("growth" in raw_query.lower() or "change" in raw_query.lower()) and len(results) > 1:
            for i in range(1, len(results)):
                prev = results[i-1].get(metric_key)
                curr = results[i].get(metric_key)
                if prev is not None and curr is not None:
                    if prev != 0:
                        results[i]['growth_pct'] = round(((curr - prev) / prev) * 100, 2)
                    else:
                        results[i]['growth_pct'] = 100.0 if curr > 0 else 0.0
    else:
        # Single value total aggregation
        row = {}
        for m in metric_cols:
            vals = [res[0][m] for res in results_per_db if res and res[0] and res[0].get(m) is not None]
            is_rate_col = any(keyword in m.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
            if is_rate_col and len(vals) > 0:
                row[m] = round(sum(vals) / len(vals), 2)
            else:
                row[m] = round(sum(vals), 2)
        results = [row]
        
    # Aggregate Contextual KPIs dynamically
    kpis = {col: 0.0 for col in kpi_candidates}
    if dynamic_metric:
        kpis[dynamic_metric] = 0.0
        
    if kpi_results_per_db:
        for res in kpi_results_per_db:
            if res and res[0]:
                for col in existing_kpis:
                    val = res[0].get(col) or 0
                    kpis[col] += val
                    
        for col in list(kpis.keys()):
            if col in existing_kpis:
                is_rate_col = any(keyword in col.lower() for keyword in ['pct', 'percentage', 'delay', 'rate'])
                if is_rate_col and len(kpi_results_per_db) > 0:
                    kpis[col] = round(kpis[col] / len(kpi_results_per_db), 2)
                else:
                    kpis[col] = round(kpis[col], 2)
            else:
                kpis[col] = 0.0

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
        "Top Capacity Plants",
        "Revenue Trend",
        "Budget Allocated by State",
        "Completion Percentage by Project Type",
        "Delay Days by Contractor"
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

from fastapi.responses import JSONResponse

@app.exception_handler(ValueError)
async def value_error_exception_handler(request, exc):
    logger.error(f"❌ Security/Validation Error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content={
            "status": "error",
            "message": f"Validation Error: {str(exc)}",
            "results": []
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"❌ Internal Server Error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content={
            "status": "error",
            "message": f"Internal Server Error: {str(exc)}",
            "results": []
        }
    )

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
                    "Top Capacity Plants",
                    "Revenue Trend",
                    "Budget Allocated by State",
                    "Completion Percentage by Project Type",
                    "Delay Days by Contractor"
                ],
                "comparisons": []
            },
            "preview": None,
            "latency_ms": (time.perf_counter() - start_time) * 1000
        }
        
    # Fast path: return cached result for previously seen prefix
    cache_key = q_trimmed.lower()
    if cache_key in SUGGEST_CACHE:
        cached = SUGGEST_CACHE[cache_key]
        cached["latency_ms"] = (time.perf_counter() - start_time) * 1000
        cached["cached"] = True
        return cached
        
    # Correct typos in the prefix to match correctly (LRU-cached internally)
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
    
    registry = MetadataRegistry.get_instance()
    
    depts = [str(v).title() for v in registry.categoricals.get("project_type", {}).get("values", [])]
    if not depts:
        depts = ["Sales", "Digital", "Marketing", "HR"]
        
    regions = [str(v).title() for v in registry.categoricals.get("location", {}).get("values", [])]
    if not regions:
        regions = ["North", "South", "East", "West", "Central"]
        
    years = [str(y) for y in registry.categoricals.get("fy_year", {}).get("values", [])]
    if not years:
        years = ["2023", "2024", "2025", "2026"]
        
    metrics = [m.replace('_', ' ').title() for m in registry.metrics.keys()]
    if not metrics:
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

    result = {
        "suggestions": {
            "metrics": [],
            "analysis": unique_completions[:5],
            "comparisons": []
        },
        "preview": preview,
        "latency_ms": latency_ms
    }
    # Store in cache (cap at 2000 entries to avoid unbounded growth)
    if len(SUGGEST_CACHE) < 2000:
        SUGGEST_CACHE[cache_key] = dict(result)
    return result

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
            return {
                "status": "error",
                "message": det_res.get("error", "Invalid year in query."),
                "results": []
            }
        if det_res and det_res["confidence"] >= 0.8:
            logger.info(f"⚡ Deterministic Parser Hit! Intent: {det_res['intent']} (Confidence: {det_res['confidence']})")
            blueprint = det_res["blueprint"]
            parsed_deterministically = True
            parser_confidence = det_res["confidence"]
            intent = det_res["intent"]
            top_n_limit = det_res.get("top_n_limit")
            top_n_asc = det_res.get("top_n_asc", False)
            
    # Fallback to Ollama only if the blueprint is completely empty/unparsed, or if metrics are missing (and it's not a profile request)
    is_profile = blueprint and any(
        any(
            SemanticSchemaProfiler.get_instance().profiles.get(p) and
            SemanticSchemaProfiler.get_instance().profiles[p].columns.get(f.get('column', '')) and
            SemanticSchemaProfiler.get_instance().profiles[p].columns[f.get('column', '')].classification == "IDENTIFIER"
            for p in POWER_PLANTS
        )
        for f in blueprint.filters
        if isinstance(f, dict) and f.get('column') not in (None, 'plant')
    )
    if payload.force_llm or not blueprint or (not blueprint.metrics and not is_profile):
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
        
    # Normalize filters to ensure standard format (unpacking list values if present)
    normalized_filters = []
    for f in blueprint.filters:
        if not isinstance(f, dict):
            continue
        if 'column' in f and 'value' in f:
            col = f['column']
            val = f['value']
            if val is None:
                continue
            val_list = val if isinstance(val, list) else [val]
            for item in val_list:
                if item is None:
                    continue
                item_str = str(item)
                item_normalized = item_str.replace(' ', '_')
                target_col = col
                if item_str.lower() in ["gujarat", "karnataka", "maharashtra", "rajasthan", "tamil nadu"]:
                    target_col = 'state'
                elif item_normalized in POWER_PLANTS:
                    target_col = 'plant'
                normalized_filters.append({"column": target_col, "value": item_str})
        else:
            for k, v in f.items():
                if v is None:
                    continue
                val_list = v if isinstance(v, list) else [v]
                for item in val_list:
                    if item is None:
                        continue
                    item_str = str(item)
                    item_normalized = item_str.replace(' ', '_')
                    target_col = k
                    if item_str.lower() in ["gujarat", "karnataka", "maharashtra", "rajasthan", "tamil nadu"]:
                        target_col = 'state'
                    elif item_normalized in POWER_PLANTS:
                        target_col = 'plant'
                    normalized_filters.append({"column": target_col, "value": item_str})
    blueprint.filters = normalized_filters

    # --- Heuristic Reinforcement for 100% Robust Parsing ---
    import re
    raw_lower = payload.raw_query.lower()

    # Hallucination check: verify if the parsed metrics are actually mentioned in the raw query text.
    if blueprint.metrics:
        valid_metrics = []
        is_breakdown = (blueprint.operation == "BREAKDOWN" or "breakdown" in raw_lower or "performance" in raw_lower)
        adapter = SemanticSchemaAdapter.get_instance()
        for m in blueprint.metrics:
            m_clean = m.replace('_', ' ')
            if is_breakdown:
                valid_metrics.append(m)
            # Check for direct mentions or synonyms
            elif m_clean in raw_lower or m.replace('_', '') in raw_lower or any(part in raw_lower for part in m.split('_') if len(part) > 3):
                valid_metrics.append(m)
            else:
                # Check adapter aliases dynamically
                aliases = adapter.column_to_aliases.get(m, set())
                matched_alias = False
                for alias in aliases:
                    alias_clean = alias.replace('_', ' ').lower()
                    if alias_clean in raw_lower:
                        matched_alias = True
                        break
                    words = [w for w in alias.split('_') if len(w) > 3]
                    if any(w in raw_lower for w in words):
                        matched_alias = True
                        break
                if matched_alias:
                    valid_metrics.append(m)
        blueprint.metrics = valid_metrics

    # 0. Year range validation — reject out-of-range years
    registry = MetadataRegistry.get_instance()
    allowed_years = registry.categoricals.get('fy_year', {}).get('values', [])
    if allowed_years:
        min_y, max_y = min(allowed_years), max(allowed_years)
    else:
        min_y, max_y = 2020, 2026

    all_years_in_query = extract_raw_year_candidates(raw_lower)
    invalid_years = [y for y in all_years_in_query if not (min_y <= int(y) <= max_y)]
    if invalid_years:
        correction = get_suggested_correction(payload.raw_query)
        err_msg = f"Ambiguity or error: The requested year {invalid_years[0]} is outside the available database bounds ({min_y} - {max_y})."
        if correction:
            err_msg += f" {correction}"
        return {
            "status": "error",
            "message": err_msg,
            "results": []
        }

    # 1. Detect compared years (more than one year like 2023, 2024)
    detected_years = extract_detected_years(raw_lower)
    if len(detected_years) > 1:
        blueprint.comparison = {"type": "year", "values": list(dict.fromkeys(detected_years))}
        blueprint.timeframe = {"type": "years", "value": ",".join(list(dict.fromkeys(detected_years)))}
        blueprint.operation = "GRAPH"
    elif len(detected_years) == 1:
        blueprint.timeframe = {"type": "year", "value": detected_years[0]}

    # 2. Detect compared categories
    adapter = SemanticSchemaAdapter.get_instance()

    # Check project types / departments
    detected_depts = []
    project_types_values = adapter.get_dimension_values("project_type")
    depts_to_check = set([v.lower() for v in project_types_values] + ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"])
    for dept in depts_to_check:
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

    dept_target_col = adapter.resolve_column_name("project_type") or "project_type"

    if len(detected_depts) > 1:
        blueprint.comparison = {"type": dept_target_col, "values": detected_depts}
        for d in detected_depts:
            if not any(f.get('column') == dept_target_col and f.get('value') == d for f in blueprint.filters):
                blueprint.filters.append({"column": dept_target_col, "value": d})
    elif len(detected_depts) == 1:
        d = detected_depts[0]
        if not any(f.get('column') == dept_target_col and f.get('value') == d for f in blueprint.filters):
            blueprint.filters.append({"column": dept_target_col, "value": d})
        
    # Check locations / regions / states
    detected_locations = []
    detected_states = []
    location_values = adapter.get_dimension_values("location")
    state_values = adapter.get_dimension_values("state")
    states_list = ["gujarat", "karnataka", "maharashtra", "rajasthan", "tamil nadu"]
    
    locations_to_check = set([v.lower() for v in location_values] + ["north", "south", "east", "west", "central"])
    for loc in locations_to_check:
        if loc in raw_lower:
            detected_locations.append(loc)
            
    for st in states_list:
        if st in raw_lower:
            detected_states.append(st)
            
    location_col = adapter.resolve_column_name("location") or "location"
    state_col = adapter.resolve_column_name("state") or "state"
    
    # Handle locations
    if len(detected_locations) > 1:
        blueprint.comparison = {"type": location_col, "values": detected_locations}
        for r in detected_locations:
            matching_val = next((v for v in location_values if str(v).lower() == r), r.capitalize())
            if not any(f.get('column') == location_col and str(f.get('value')).lower() == r for f in blueprint.filters):
                blueprint.filters.append({"column": location_col, "value": matching_val})
    elif len(detected_locations) == 1:
        r = detected_locations[0]
        matching_val = next((v for v in location_values if str(v).lower() == r), r.capitalize())
        if not any(f.get('column') == location_col and str(f.get('value')).lower() == r for f in blueprint.filters):
            blueprint.filters.append({"column": location_col, "value": matching_val})
            
    # Handle states
    if len(detected_states) > 1:
        blueprint.comparison = {"type": state_col, "values": detected_states}
        for s in detected_states:
            matching_val = next((v for v in state_values if str(v).lower() == s), s.capitalize())
            if not any(f.get('column') == state_col and str(f.get('value')).lower() == s for f in blueprint.filters):
                blueprint.filters.append({"column": state_col, "value": matching_val})
    elif len(detected_states) == 1:
        s = detected_states[0]
        matching_val = next((v for v in state_values if str(v).lower() == s), s.capitalize())
        if not any(f.get('column') == state_col and str(f.get('value')).lower() == s for f in blueprint.filters):
            blueprint.filters.append({"column": state_col, "value": matching_val})

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
            resolved_detected = []
            for dm in detected_metrics:
                resolved_dm = SemanticSchemaAdapter.get_instance().resolve_column_name(dm)
                if resolved_dm:
                    resolved_detected.append(resolved_dm)
                else:
                    resolved_detected.append(dm)
            blueprint.metrics = list(dict.fromkeys(resolved_detected))
        
    is_profile_query = blueprint and any(
        any(
            SemanticSchemaProfiler.get_instance().profiles.get(p) and
            SemanticSchemaProfiler.get_instance().profiles[p].columns.get(f.get('column', '')) and
            SemanticSchemaProfiler.get_instance().profiles[p].columns[f.get('column', '')].classification == "IDENTIFIER"
            for p in POWER_PLANTS
        )
        for f in blueprint.filters
        if isinstance(f, dict) and f.get('column') not in (None, 'plant')
    )
    if not blueprint.metrics and not is_profile_query:
        logger.info(f"📊 No metrics specified, defaulting to all core metrics")
        blueprint.metrics = SemanticSchemaAdapter.get_instance().kpi_candidates or ["revenue", "profit", "expenses", "headcount"]

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
            "intent": intent,
            "sources": execution_data.get("plants_queried", len(POWER_PLANTS))
        }
        return execution_data

    execution_data = await federated_query_processor(blueprint, payload.raw_query, payload.parsing_metadata)
    
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
        "intent": intent,
        "sources": execution_data.get("plants_queried", len(POWER_PLANTS))
    }
    return execution_data

@app.get("/api/metadata")
def get_metadata():
    registry = MetadataRegistry.get_instance()
    return {"metrics": list(registry.metrics.keys()), "categoricals": {k: list(v["values"]) for k,v in registry.categoricals.items()}}

@app.get("/")
def health(): return {"status": "online"}
