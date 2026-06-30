import sys
import os
# Ensure the parent directory of backend is in the path to allow resolving 'backend.xxx' imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import time
import logging
import hashlib
import threading
import json
import sqlite3
from collections import defaultdict
from typing import List, Dict, Any, Optional
import duckdb

logger = logging.getLogger("alphabot.cache")

# Thread-local storage to hold separate DuckDB connections per thread
_thread_local = threading.local()

class SessionResultCacheManager:
    """Thread-safe manager implementing IQP Phase 2 caching, pooling, and governance."""
    _instance = None
    _lock = threading.Lock()
    _version_cache = {}
    
    # Governance ceilings
    SOFT_LIMIT_BYTES = 800 * 1024 * 1024  # 800 MB
    HARD_LIMIT_BYTES = 1200 * 1024 * 1024  # 1.2 GB
    
    @classmethod
    def get_instance(cls) -> "SessionResultCacheManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        # We store table metadata in memory for fast lookup, synced to SQLite query_history / catalog
        self.catalog = defaultdict(dict)  # session_id -> {node_id: metadata_dict}
        self.lock = threading.RLock()
        self.session_activity = []  # LRU list of session_ids
        # Single shared in-memory database instance
        self.db = duckdb.connect(database=":memory:")
        self.db.execute("SET max_memory='2GB'")
        try:
            self.db.execute("INSTALL json; LOAD json;")
        except Exception as e:
            logger.warning(f"Failed to pre-load json extension: {e}")

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Returns the thread-local DuckDB connection cursor sharing the main memory database."""
        if not hasattr(_thread_local, "con"):
            _thread_local.con = self.db.cursor()
        return _thread_local.con

    def _estimate_rows_size(self, rows: List[Dict[str, Any]]) -> int:
        """Estimates memory size of rows in bytes (approx 100 bytes per cell)."""
        if not rows:
            return 0
        num_cells = len(rows) * len(rows[0])
        return num_cells * 100

    def _update_activity(self, session_id: str):
        """Helper to maintain LRU access list for session eviction."""
        if session_id in self.session_activity:
            self.session_activity.remove(session_id)
        self.session_activity.append(session_id)

    def get_active_memory_usage(self) -> int:
        """Calculates total memory size of all active tables in bytes."""
        total = 0
        with self.lock:
            for session_id, nodes in self.catalog.items():
                for node_id, entry in nodes.items():
                    total += entry.get("memory_size", 0)
        return total

    def enforce_memory_governance(self, new_bytes: int):
        """Enforces soft and hard memory ceilings, running LRU eviction if needed."""
        total_used = self.get_active_memory_usage()
        projected = total_used + new_bytes
        
        if projected > self.HARD_LIMIT_BYTES:
            logger.warning(f"⚠️ Cache hard limit breached ({projected / 1e6:.1f} MB > {self.HARD_LIMIT_BYTES / 1e6:.1f} MB). Running sync eviction.")
            self._run_eviction_loop(target_limit=self.SOFT_LIMIT_BYTES)
        elif projected > self.SOFT_LIMIT_BYTES:
            logger.info(f"ℹ️ Cache soft limit reached ({projected / 1e6:.1f} MB). Triggering async eviction.")
            # Run eviction in background thread
            threading.Thread(target=self._run_eviction_loop, args=(self.SOFT_LIMIT_BYTES,)).start()

    def _run_eviction_loop(self, target_limit: int):
        """Evicts oldest sessions until catalog size satisfies the target limit."""
        with self.lock:
            while self.get_active_memory_usage() > target_limit and self.session_activity:
                # Evict oldest session
                oldest_session = self.session_activity.pop(0)
                logger.info(f"🧹 Evicting session {oldest_session} to free memory.")
                
                # Fetch tables to drop
                nodes = list(self.catalog.get(oldest_session, {}).keys())
                con = self._get_connection()
                for nid in nodes:
                    table_name = self.catalog[oldest_session][nid]["table_name"]
                    try:
                        con.execute(f"DROP TABLE IF EXISTS {table_name}")
                    except Exception as e:
                        logger.warning(f"Error dropping table {table_name}: {e}")
                
                if oldest_session in self.catalog:
                    del self.catalog[oldest_session]

    def has_cache(self, session_id: str, node_id: int) -> bool:
        """Returns True if the node cache is active and exists."""
        with self.lock:
            session_catalog = self.catalog.get(session_id, {})
            if node_id in session_catalog:
                session_catalog[node_id]["last_used"] = time.time()
                self._update_activity(session_id)
                return True
        return False

    def save_cache(self, session_id: str, node_id: int, rows: List[Dict[str, Any]], db_version_hash: str) -> Optional[str]:
        """Saves a list of rows as an in-memory DuckDB table and registers to catalog."""
        if not rows:
            return None
            
        est_size = self._estimate_rows_size(rows)
        self.enforce_memory_governance(est_size)
        
        table_name = f"session_{session_id.replace('-', '_')}_node_{node_id}"
        con = self._get_connection()
        
        try:
            import pandas as pd
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
            
            # Load list of dicts to pandas DataFrame and create the DuckDB table directly
            df = pd.DataFrame(rows)
            con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
            
            with self.lock:
                self.catalog[session_id][node_id] = {
                    "table_name": table_name,
                    "created_at": time.time(),
                    "last_used": time.time(),
                    "memory_size": est_size,
                    "db_version_hash": db_version_hash,
                    "row_count": len(rows)
                }
                self._update_activity(session_id)
            
            logger.info(f"💾 Cached table {table_name} created successfully ({len(rows)} rows, ~{est_size/1024:.1f} KB).")
            return table_name
        except Exception as e:
            logger.error(f"Failed to cache table {table_name} in DuckDB: {e}")
            return None

    @property
    def last_query_ms(self) -> float:
        return getattr(_thread_local, "last_query_ms", 0.0)

    @property
    def last_serialization_ms(self) -> float:
        return getattr(_thread_local, "last_serialization_ms", 0.0)

    @property
    def last_serialization_method(self) -> str:
        return getattr(_thread_local, "last_serialization_method", "none")

    @property
    def last_rows_serialized(self) -> int:
        return getattr(_thread_local, "last_rows_serialized", 0)

    def query_cache(self, session_id: str, node_id: int, sql_query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Queries a DuckDB cached table locally using fast C++ JSON serialization and orjson."""
        con = self._get_connection()
        
        with self.lock:
            if session_id not in self.catalog or node_id not in self.catalog[session_id]:
                raise ValueError(f"Cache table not registered for session {session_id} node {node_id}")
            entry = self.catalog[session_id][node_id]
            table_name = entry["table_name"]
            
        inner_query = sql_query.replace("{table_name}", table_name)
        wrapped_query = f"SELECT CAST(json_group_array(to_json(t)) AS VARCHAR) FROM ({inner_query}) t"
        
        try:
            import orjson
        except ImportError:
            import json as orjson
            
        try:
            t0 = time.perf_counter()
            cursor = con.execute(wrapped_query, params)
            t1 = time.perf_counter()
            
            res_str = cursor.fetchone()[0]
            results = orjson.loads(res_str or "[]")
            t2 = time.perf_counter()
            
            _thread_local.last_query_ms = (t1 - t0) * 1000.0
            _thread_local.last_serialization_ms = (t2 - t1) * 1000.0
            _thread_local.last_serialization_method = "duckdb_json_orjson" if "orjson" in sys.modules else "duckdb_json_json"
            _thread_local.last_rows_serialized = len(results)
            
            with self.lock:
                entry["last_used"] = time.time()
                self._update_activity(session_id)
            return results
        except Exception as e:
            logger.error(f"DuckDB local execution failed: {e}")
            raise e

    def clone_cache_subset(self, session_id: str, parent_node_id: int, child_node_id: int, sql_query: str, params: tuple, db_version_hash: str) -> int:
        """Clones a raw subset of rows directly inside DuckDB from parent to child table, bypassing Python serialization."""
        con = self._get_connection()
        
        with self.lock:
            if session_id not in self.catalog or parent_node_id not in self.catalog[session_id]:
                raise ValueError(f"Parent cache table not registered for session {session_id} node {parent_node_id}")
            parent_entry = self.catalog[session_id][parent_node_id]
            parent_table_name = parent_entry["table_name"]
            
        child_table_name = f"session_{session_id.replace('-', '_')}_node_{child_node_id}"
        
        query = sql_query.replace("{table_name}", parent_table_name)
        create_sql = f"CREATE TABLE {child_table_name} AS {query}"
        
        try:
            con.execute(f"DROP TABLE IF EXISTS {child_table_name}")
            con.execute(create_sql, params)
            
            # Retrieve count
            row_count = con.execute(f"SELECT COUNT(*) FROM {child_table_name}").fetchone()[0]
            est_size = self._estimate_rows_size([{"dummy": 0}] * row_count)
            
            with self.lock:
                self.catalog[session_id][child_node_id] = {
                    "table_name": child_table_name,
                    "created_at": time.time(),
                    "last_used": time.time(),
                    "memory_size": est_size,
                    "db_version_hash": db_version_hash,
                    "row_count": row_count
                }
                self._update_activity(session_id)
                
            logger.info(f"💾 Vectorized clone table {child_table_name} created directly in DuckDB ({row_count} rows, ~{est_size/1024:.1f} KB).")
            
            _thread_local.last_query_ms = 0.0
            _thread_local.last_serialization_ms = 0.0
            _thread_local.last_serialization_method = "duckdb_cloned_vectorized"
            _thread_local.last_rows_serialized = 0
            
            return row_count
        except Exception as e:
            logger.error(f"Failed to clone cache table in DuckDB: {e}")
            raise e

    @property
    def last_version_cache_hit(self) -> bool:
        return getattr(_thread_local, "last_version_cache_hit", False)

    @property
    def last_freshness_method(self) -> str:
        return getattr(_thread_local, "last_freshness_method", "queried")

    def get_composite_version_hash(self, plants: List[str]) -> str:
        """Fetches PRAGMA data_version from SQLite database connections with caching and returns an MD5 hash."""
        from backend.main import ConnectionManager
        version_tokens = []
        now = time.time()
        ttl = 2.5
        
        cache_hit = True
        
        for plant in sorted(plants):
            cached = self._version_cache.get(plant)
            if cached and (now - cached["timestamp"]) < ttl:
                ver = cached["version"]
            else:
                cache_hit = False
                db_path = ConnectionManager.db_path(plant)
                ver = 0
                if os.path.exists(db_path):
                    try:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute("PRAGMA data_version")
                        ver = cursor.fetchone()[0]
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Failed to fetch data_version for plant {plant}: {e}")
                
                self._version_cache[plant] = {
                    "version": ver,
                    "timestamp": now
                }
                
            version_tokens.append(f"{plant}:{ver}")
            
        _thread_local.last_version_cache_hit = cache_hit
        _thread_local.last_freshness_method = "cached" if cache_hit else "queried"
        
        version_str = "|".join(version_tokens)
        return hashlib.md5(version_str.encode()).hexdigest()

    def check_cache_freshness(self, session_id: str, node_id: int, plants: List[str]) -> bool:
        """Verifies if the stored data_version hash matches the current composite versions."""
        with self.lock:
            if session_id not in self.catalog or node_id not in self.catalog[session_id]:
                return False
            entry = self.catalog[session_id][node_id]
            cached_hash = entry.get("db_version_hash", "")
            
        current_hash = self.get_composite_version_hash(plants)
        return cached_hash == current_hash

    def drop_node_cache(self, session_id: str, node_id: int):
        """Drops a cache table and deletes catalog registration."""
        table_name = f"session_{session_id.replace('-', '_')}_node_{node_id}"
        con = self._get_connection()
        try:
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
        except Exception as e:
            logger.warning(f"Error dropping table {table_name}: {e}")
            
        with self.lock:
            if session_id in self.catalog and node_id in self.catalog[session_id]:
                del self.catalog[session_id][node_id]

    def clear_session(self, session_id: str):
        """Evicts all tables and catalog configurations for the session."""
        with self.lock:
            if session_id not in self.catalog:
                return
            nodes = list(self.catalog[session_id].keys())
            
        con = self._get_connection()
        for nid in nodes:
            table_name = f"session_{session_id.replace('-', '_')}_node_{nid}"
            try:
                con.execute(f"DROP TABLE IF EXISTS {table_name}")
            except Exception as e:
                logger.warning(f"Error dropping table {table_name}: {e}")
                
        with self.lock:
            if session_id in self.catalog:
                del self.catalog[session_id]
            if session_id in self.session_activity:
                self.session_activity.remove(session_id)
