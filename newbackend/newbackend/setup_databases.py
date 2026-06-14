
import sqlite3
import random
import os
from datetime import datetime, timedelta

# Reverting to the original power plant naming convention
POWER_PLANTS = [
    "diablo_canyon", "three_mile_island", "palo_verde", 
    "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"
]

PROJECT_TYPES = ["Solar", "Wind", "Hybrid", "Hybrid-Wind", "Hybrid-Solar"]
CATEGORIES = ["Strategic", "Standard", "Expansion", "Greenfield", "Brownfield"]
CONTRACTORS = ["L&T", "Tata Power", "Adani Infra", "Sterling & Wilson", "Siemens", "GE Power", "Suzlon"]
MATERIAL_STATUS = ["Ordered", "In Transit", "Customs Cleared", "At Site", "Installed"]
PAYMENT_STATUS = ["Pending", "Advance Paid", "Milestone 1 Cleared", "Milestone 2 Cleared", "Fully Paid"]

# Scaling to >2 Lakh rows per DB as requested
RECORDS_PER_DB = 280000 

def create_single_database(plant_name: str):
    db_name = f"{plant_name}.db"
    table_name = f"metrics_{plant_name}"
    
    # Force cleanup: Delete existing DB to start fresh with new schema
    if os.path.exists(db_name):
        try:
            os.remove(db_name)
            print(f"Cleanup: Deleted {db_name}")
        except Exception as e:
            print(f"Cleanup Error on {db_name}: {e}")

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # 22-column complex schema from the Project Master
    cursor.execute(f"""
    CREATE TABLE {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id VARCHAR(20),
        project_name VARCHAR(100),
        project_type VARCHAR(20),
        location VARCHAR(50),
        state VARCHAR(50),
        capacity_mw NUMERIC,
        record_date TIMESTAMP NOT NULL,
        fy_year INTEGER,
        category VARCHAR(20),
        budget_allocated NUMERIC,
        budget_used NUMERIC,
        budget_remaining NUMERIC,
        revenue NUMERIC,
        scheduled_comm_date DATE,
        expected_comm_date DATE,
        actual_comm_date DATE,
        contractor_name VARCHAR(100),
        material VARCHAR(50),
        material_status VARCHAR(50),
        contractor_payment_status VARCHAR(50),
        completion_percentage NUMERIC,
        delay_days INTEGER,
        remarks TEXT
    );
    """)
    conn.commit()

    # Create indexes for high-performance filtering
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{plant_name}_project_type ON {table_name}(project_type);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{plant_name}_location ON {table_name}(location);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{plant_name}_state ON {table_name}(state);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{plant_name}_record_date ON {table_name}(record_date);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{plant_name}_fy_year ON {table_name}(fy_year);")
    conn.commit()

    print(f"🚀 Populating {RECORDS_PER_DB} complex records for {db_name}...")
    start_date = datetime(2020, 1, 1)
    
    chunk_size = 20000
    for chunk_start in range(0, RECORDS_PER_DB, chunk_size):
        records = []
        actual_chunk_size = min(chunk_size, RECORDS_PER_DB - chunk_start)
        
        for i in range(actual_chunk_size):
            global_idx = chunk_start + i
            # Extended timeline to 2027
            date = start_date + timedelta(days=random.randint(0, 365 * 7), hours=random.randint(0, 23))
            
            proj_type = random.choice(PROJECT_TYPES)
            budget = round(random.uniform(500, 10000), 2)
            used = round(budget * random.uniform(0.1, 0.9), 2)
            
            records.append((
                f"PRJ-{plant_name[:3].upper()}-{global_idx:06d}",
                f"{plant_name.replace('_', ' ').title()} {proj_type} Unit {random.randint(1,9)}",
                proj_type,
                plant_name.replace('_', ' ').capitalize(),
                random.choice(["Gujarat", "Rajasthan", "Karnataka", "Maharashtra", "Tamil Nadu"]),
                round(random.uniform(50, 1200), 2),
                date.strftime("%Y-%m-%d %H:%M:%S"),
                date.year,
                random.choice(CATEGORIES),
                budget,
                used,
                round(budget - used, 2),
                round(random.uniform(10, 800), 2),
                (date + timedelta(days=365)).strftime("%Y-%m-%d"),
                (date + timedelta(days=400)).strftime("%Y-%m-%d"),
                (date + timedelta(days=420)).strftime("%Y-%m-%d"),
                random.choice(CONTRACTORS),
                "PV Modules" if "Solar" in proj_type else "Wind Turbines",
                random.choice(MATERIAL_STATUS),
                random.choice(PAYMENT_STATUS),
                round(random.uniform(0, 100), 2),
                random.randint(0, 200),
                "Operational data update"
            ))

        cursor.executemany(f"""
        INSERT INTO {table_name} (
            project_id, project_name, project_type, location, state, capacity_mw, 
            record_date, fy_year, category, budget_allocated, budget_used, 
            budget_remaining, revenue, scheduled_comm_date, expected_comm_date, 
            actual_comm_date, contractor_name, material, material_status, 
            contractor_payment_status, completion_percentage, delay_days, remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, records)
        conn.commit()

    conn.close()
    print(f"✅ {db_name} finalized.")

if __name__ == "__main__":
    for plant in POWER_PLANTS:
        create_single_database(plant)
    print("\n--- Massive Multi-Source Environment (v2.1) Ready ---")
