import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import sqlite3

# Import the objects we need to test
from main import app, MetadataRegistry, build_federated_query_parts, Blueprint, POWER_PLANTS

# --- Test Setup and Teardown ---
@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown_for_tests():
    """
    Overrides the MetadataRegistry singleton instance with mock metadata
    so that unit and integration tests run hermetically regardless of local database state.
    """
    registry = MetadataRegistry.get_instance()
    
    # Pre-populate with all metrics and categoricals used in test assertions
    registry.metrics = {
        "revenue": {"column": "revenue", "type": "NUMERIC"},
        "budget_allocated": {"column": "budget_allocated", "type": "NUMERIC"},
        "budget_used": {"column": "budget_used", "type": "NUMERIC"},
        "capacity_mw": {"column": "capacity_mw", "type": "NUMERIC"},
        "completion_percentage": {"column": "completion_percentage", "type": "NUMERIC"},
        "delay_days": {"column": "delay_days", "type": "NUMERIC"}
    }
    
    registry.categoricals = {
        "location": {"values": ["Hinkley point", "Vogtle", "Darlington", "Gujarat"]},
        "project_type": {"values": ["Solar", "Wind", "Hybrid"]},
        "project_id": {"values": ["PRJ-DAR-000001", "PRJ-VOG-000002"]},
        "fy_year": {"values": [2023, 2024, 2025, 2026]},
        "contractor_name": {"values": ["Tata Power", "L&T", "Adani Infra"]},
        "material_status": {"values": ["Installed", "Ordered", "In Transit"]},
        "category": {"values": ["Strategic", "Standard", "Expansion"]}
    }
    registry._initialized = True
    
    with patch('os.path.exists', return_value=True):
        yield

@pytest.fixture(scope="function")
def client():
    """Provides a new TestClient for each integration test."""
    with TestClient(app) as c:
        yield c

# --- Unit Tests for Logic ---
def test_build_federated_query_parts_simple():
    bp = Blueprint(metrics=["revenue"])
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert where == ""
    assert metrics == ["revenue"]
    assert params == ()

def test_build_federated_query_parts_with_filters():
    bp = Blueprint(metrics=["budget_allocated"], filters=[{"column": "location", "value": "Darlington"}])
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert where == "location = ?"
    assert metrics == ["budget_allocated"]
    assert params == ("Darlington",)

def test_build_federated_query_parts_with_timeframe():
    bp = Blueprint(metrics=["capacity_mw"], timeframe={"type": "year", "value": "2025"})
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert "fy_year = ?" in where
    assert metrics == ["capacity_mw"]
    assert params == (2025,)

# --- Integration Tests for API Endpoint ---
@patch('main.run_query_on_single_db')
def test_total_revenue_query(mock_run_query, client):
    mock_run_query.return_value = [{"revenue": 1000}]
    payload = {"raw_query": "what is total revenue", "blueprint": {"metrics": ["revenue"]}}
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["results"][0]["revenue"] == 1000 * len(POWER_PLANTS)

@patch('main.run_query_on_single_db')
def test_filtered_headcount_query(mock_run_query, client):
    mock_run_query.return_value = [{"capacity_mw": 10}]
    payload = {
        "raw_query": "capacity for Solar",
        "blueprint": {"metrics": ["capacity_mw"], "filters": [{"column": "project_type", "value": "Solar"}]}
    }
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["results"][0]["capacity_mw"] == 10 * len(POWER_PLANTS)

@patch('main.run_query_on_single_db')
def test_multi_metric_breakdown_query(mock_run_query, client):
    mock_run_query.return_value = [{
        "revenue": 900000.0, "capacity_mw": 100.0, "budget_allocated": 800000.0,
        "budget_used": 420000.0, "completion_percentage": 75.0, "delay_days": 15
    }]
    payload = {
        "raw_query": "what is the breakdown of Solar project_type in 2026 of grand_gulf in Gujarat location",
        "blueprint": {
            "operation": "BREAKDOWN",
            "comparison": {"type": "plant"},
            "metrics": ["revenue", "capacity_mw", "budget_allocated", "budget_used", "completion_percentage", "delay_days"],
            "filters": [
                {"column": "project_type", "value": "Solar"},
                {"column": "plant", "value": "grand_gulf"},
                {"column": "location", "value": "Gujarat"}
            ],
            "timeframe": {"type": "year", "value": "2026"}
        }
    }
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert len(data["results"]) == 1
    assert data["results"][0]["revenue"] == 900000.0
    assert data["results"][0]["capacity_mw"] == 100.0
    assert data["results"][0]["budget_allocated"] == 800000.0
    assert data["results"][0]["budget_used"] == 420000.0
    assert data["results"][0]["completion_percentage"] == 75.0
    assert data["results"][0]["delay_days"] == 15
    assert data["plants_queried"] == 1

def test_health_check(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "online"}

def test_deterministic_parser_word_boundaries_and_top_n():
    from main import parse_query_deterministically
    
    # 1. Word boundary check
    res_through = parse_query_deterministically("budget allocated breakdown by department at palo verde from 2022 through 2026")
    assert res_through is not None
    
    # 2. top_n subject rank check ('top plants' should have 'plant' as comparison dimension)
    res_top = parse_query_deterministically("top plants by revenue from 2023 to 2026")
    assert res_top is not None
    assert res_top["blueprint"].comparison == {"type": "plant"}

def test_dynamic_categorical_and_dimension_parsing():
    from main import parse_query_deterministically, build_federated_query_parts
    
    # 1. Test parsing of dynamic filters
    res = parse_query_deterministically("budget allocated for Tata Power in Gujarat")
    assert res is not None
    bp = res["blueprint"]
    assert any(f["column"] == "contractor_name" and f["value"] == "Tata Power" for f in bp.filters)
    assert any(f["column"] == "location" and f["value"] == "Gujarat" for f in bp.filters)
    
    # 2. Test aliases in build_federated_query_parts
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert "contractor_name = ?" in where
    assert "location = ?" in where
    
    # 3. Test comparison dimension alias parsing
    res_comp = parse_query_deterministically("compare budget used by contractor")
    assert res_comp is not None
    assert res_comp["blueprint"].comparison == {"type": "contractor_name"}

def test_sql_injection_rejection():
    from main import Blueprint, build_federated_query_parts
    import pytest
    
    # 1. Inject in filter column
    bp_bad_col = Blueprint(metrics=["revenue"], filters=[{"column": "1; DROP TABLE metrics_darlington; --", "value": "Gujarat"}])
    with pytest.raises(ValueError) as exc:
        build_federated_query_parts(bp_bad_col)
    assert "Invalid or unauthorized filter column" in str(exc.value)

    # 2. Inject in metrics list
    bp_bad_metric = Blueprint(metrics=["1; SELECT * FROM sqlite_master; --"])
    with pytest.raises(ValueError) as exc:
        build_federated_query_parts(bp_bad_metric)
    assert "Invalid or unauthorized metric requested" in str(exc.value)

    # 3. Inject in comparison operator
    bp_bad_op = Blueprint(metrics=["revenue"], comparison={"metric": "revenue", "operator": "1; DROP TABLE --", "value": "100"})
    with pytest.raises(ValueError) as exc:
        build_federated_query_parts(bp_bad_op)
    assert "Invalid comparison operator" in str(exc.value)

def test_explicit_breakdown_by_support():
    from main import Blueprint, build_federated_query_parts
    
    # Test breakdown_by department maps to project_type
    bp = Blueprint(operation="BREAKDOWN", metrics=["revenue"], breakdown_by="department")
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp)
    assert "project_type" in sql_select
    assert "project_type" in sql_group_by
    
    # Test breakdown_by contractor maps to contractor_name
    bp_contractor = Blueprint(operation="BREAKDOWN", metrics=["revenue"], breakdown_by="contractor")
    where, metrics, params, sql_select, sql_group_by, sql_order_by = build_federated_query_parts(bp_contractor)
    assert "contractor_name" in sql_select
    assert "contractor_name" in sql_group_by

def test_environment_variable_path_load():
    import os
    from unittest.mock import patch
    
    with patch.dict(os.environ, {"ALPHABOT_DB_DIR": "C:\\MockDbDir"}):
        import importlib
        import main
        importlib.reload(main)
        assert main.BASE_DIR == "C:\\MockDbDir"
    
    # Restore defaults
    import importlib
    import main
    importlib.reload(main)

def test_semantic_schema_adapter():
    from main import SemanticSchemaAdapter, MetadataRegistry
    
    adapter = SemanticSchemaAdapter.get_instance()
    registry = MetadataRegistry.get_instance()
    
    # Assert build_schema_maps works and populates mapping
    adapter.build_schema_maps(registry)
    assert adapter._initialized is True
    
    # Assert resolve_column_name handles exact match, synonyms, and underscores/spaces
    assert adapter.resolve_column_name("project_type") == "project_type"
    assert adapter.resolve_column_name("department") == "project_type"
    assert adapter.resolve_column_name("vendor") == "contractor_name"
    assert adapter.resolve_column_name("contractor name") == "contractor_name"
    assert adapter.resolve_column_name("territory") == "location"
    assert adapter.resolve_column_name("partner") == "contractor_name"
    
    # Assert get_dimension_values returns correct categorical values
    vals = adapter.get_dimension_values("department")
    assert "Solar" in vals
    assert "Wind" in vals
    
    # Assert dynamically generated defaults
    assert "revenue" in adapter.kpi_candidates
    assert "capacity_mw" in adapter.kpi_candidates
    assert "project_type" in adapter.grouping_dimensions
    assert "location" in adapter.grouping_dimensions


@patch('main.run_query_on_single_db')
def test_project_id_profile_query(mock_run_query, client):
    mock_run_query.return_value = [{"project_id": "PRJ-DAR-000001", "project_name": "Darlington Wind Unit 7", "revenue": 706.01}]
    payload = {"raw_query": "PRJ-DAR-000001", "blueprint": None}
    response = client.post("/api/query", json=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["results"][0]["project_id"] == "PRJ-DAR-000001"
    assert data["unit"] == "RawData"
    assert data["plants_queried"] == 1


def test_project_id_spelling_and_components():
    from main import get_suggested_correction, extract_query_components, parse_query_deterministically
    
    q = "PRJ-DAR-000001"
    # Verify no correction is suggested (i.e. not flagged as gibberish)
    assert get_suggested_correction(q) is None
    
    # Verify project_id component is extracted
    components = extract_query_components(q)
    assert "project_id" in components["categoricals"]
    assert "PRJ-DAR-000001" in components["categoricals"]["project_id"]
    
    # Verify deterministic parsing
    parsed = parse_query_deterministically(q)
    assert parsed is not None
    assert parsed["blueprint"].metrics == []
    assert any(f["column"] == "project_id" and f["value"] == "PRJ-DAR-000001" for f in parsed["blueprint"].filters)


def test_semantic_schema_profiler():
    from main import SemanticSchemaProfiler, MetadataRegistry
    
    profiler = SemanticSchemaProfiler.get_instance()
    registry = MetadataRegistry.get_instance()
    
    profiler.profile_databases(registry)
    assert profiler._initialized is True
    
    # Assert profiles exist
    assert len(profiler.profiles) > 0
    
    # Let's inspect a sample plant profile
    plant_profile = list(profiler.profiles.values())[0]
    assert plant_profile.database_name is not None
    assert plant_profile.table_name is not None
    
    # Verify classifications and structures on columns
    for col_name, col_prof in plant_profile.columns.items():
        assert col_prof.classification in ["METRIC", "DIMENSION", "IDENTIFIER", "STATUS", "TIME"]
        assert col_prof.data_type is not None
        assert col_name in col_prof.aliases
        
    # Verify defaults are generated
    assert len(plant_profile.defaults.get("kpi_candidates", [])) > 0
    assert len(plant_profile.defaults.get("grouping_dimensions", [])) > 0


def test_schema_generalization(tmp_path, monkeypatch):
    import os
    import sqlite3
    import importlib
    
    # 1. Create synthetic databases
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    
    # Database A
    db_a_path = db_dir / "db_a.db"
    conn = sqlite3.connect(db_a_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE metrics_db_a (
        asset_code TEXT PRIMARY KEY,
        facility_name TEXT,
        energy_output REAL,
        vendor TEXT,
        commission_date TEXT
    )
    """)
    cursor.executemany("INSERT INTO metrics_db_a VALUES (?, ?, ?, ?, ?)", [
        ("AST-001", "Wind Station A", 450.5, "Siemens", "2022-01-15"),
        ("AST-002", "Solar Field B", 1200.0, "GE", "2023-06-20"),
    ])
    conn.commit()
    conn.close()
    
    # Database B
    db_b_path = db_dir / "db_b.db"
    conn = sqlite3.connect(db_b_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE metrics_db_b (
        warehouse_id TEXT PRIMARY KEY,
        supplier_name TEXT,
        stock_value REAL,
        inventory_turnover REAL,
        fiscal_year INTEGER
    )
    """)
    cursor.executemany("INSERT INTO metrics_db_b VALUES (?, ?, ?, ?, ?)", [
        ("WH-001", "Logistics Inc", 150000.0, 4.5, 2022),
    ])
    conn.commit()
    conn.close()

    # Database C
    db_c_path = db_dir / "db_c.db"
    conn = sqlite3.connect(db_c_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE metrics_db_c (
        contract_ref TEXT PRIMARY KEY,
        client_name TEXT,
        project_cost REAL,
        delivery_status TEXT,
        completion_date TEXT
    )
    """)
    cursor.executemany("INSERT INTO metrics_db_c VALUES (?, ?, ?, ?, ?)", [
        ("CON-001", "Alpha Corp", 750000.0, "Delivered", "2022-12-31"),
    ])
    conn.commit()
    conn.close()

    # Setup environment overrides and reload main to initialize registry on db_dir
    monkeypatch.setenv("ALPHABOT_DB_DIR", str(db_dir))
    import main
    importlib.reload(main)

    from main import MetadataRegistry, SemanticSchemaProfiler, SemanticSchemaAdapter, app
    from fastapi.testclient import TestClient

    # Force registry and adapter to initialize on our synthetic DBs
    registry = MetadataRegistry.get_instance()
    registry._initialized = False
    registry.initialize()

    # Assert discovered tables
    assert "db_a" in registry.table_names
    assert "db_b" in registry.table_names
    assert "db_c" in registry.table_names

    profiler = SemanticSchemaProfiler.get_instance()
    
    # Db A checks
    prof_a = profiler.profiles["db_a"]
    assert prof_a.columns["energy_output"].classification == "METRIC"
    assert prof_a.columns["facility_name"].classification == "DIMENSION"
    assert prof_a.columns["commission_date"].classification == "TIME"

    # Db B checks
    prof_b = profiler.profiles["db_b"]
    assert prof_b.columns["stock_value"].classification == "METRIC"
    assert prof_b.columns["inventory_turnover"].classification == "METRIC"
    assert prof_b.columns["supplier_name"].classification == "DIMENSION"
    assert prof_b.columns["fiscal_year"].classification == "TIME"

    # Db C checks
    prof_c = profiler.profiles["db_c"]
    assert prof_c.columns["project_cost"].classification == "METRIC"
    assert prof_c.columns["client_name"].classification == "DIMENSION"
    assert prof_c.columns["completion_date"].classification == "TIME"
    assert prof_c.columns["delivery_status"].classification == "STATUS"

    # Check dynamic mapping in adapter
    adapter = SemanticSchemaAdapter.get_instance()
    assert adapter.resolve_column_name("facility name") == "facility_name"
    assert adapter.resolve_column_name("vendor") == "vendor"
    assert adapter.resolve_column_name("stock value") == "stock_value"
    assert adapter.resolve_column_name("project cost") == "project_cost"

    # Mock Ollama fallback since it can be slow/offline
    from main import Blueprint
    mock_bp = Blueprint()
    mock_bp.metrics = ["energy_output"]
    mock_bp.operation = "BREAKDOWN"
    mock_bp.comparison = {"type": "vendor"}

    from unittest.mock import AsyncMock
    mock_call = AsyncMock(return_value=mock_bp)
    monkeypatch.setattr("main.call_ollama_fallback", mock_call)

    # Use TestClient to verify API handling
    with TestClient(app) as client:
        # Query Db A (Ollama fallback)
        res_a = client.post("/api/query", json={"raw_query": "energy output by vendor in db_a", "blueprint": None})
        assert res_a.status_code == 200
        assert res_a.json()["status"] == "success"
        assert len(res_a.json()["results"]) > 0

        # Query Db C (Deterministic parser)
        res_c = client.post("/api/query", json={"raw_query": "project cost by delivery status in db_c", "blueprint": None})
        assert res_c.status_code == 200
        assert res_c.json()["status"] == "success"
        assert len(res_c.json()["results"]) > 0

    # Restore default main environment for remaining tests
    monkeypatch.delenv("ALPHABOT_DB_DIR", raising=False)
    importlib.reload(main)
    main.MetadataRegistry.get_instance()._initialized = False
    main.MetadataRegistry.get_instance().initialize()




