import sqlite3
import os
import glob
import time

def add_indexes_to_db(db_path):
    print(f"Processing {os.path.basename(db_path)}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Find the metrics table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
        row = cursor.fetchone()
        if not row:
            print(f"  No metrics table found in {db_path}")
            return
        
        table_name = row[0]
        
        # Create indexes for physical columns in the schema
        print(f"  Creating indexes on {table_name}...")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_record_date ON {table_name}(record_date)")
        
        # Check if new schema columns exist before creating indexes
        cursor.execute(f"PRAGMA table_info({table_name})")
        cols = [r[1] for r in cursor.fetchall()]
        
        if "state" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_state ON {table_name}(state)")
        if "fy_year" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_fy_year ON {table_name}(fy_year)")
        if "project_type" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_project_type ON {table_name}(project_type)")
        if "location" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_location ON {table_name}(location)")
            
        # Composite indexes for subset query combinations
        if "state" in cols and "fy_year" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_state_fy ON {table_name}(state, fy_year)")
        if "state" in cols and "project_type" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_state_proj ON {table_name}(state, project_type)")
        if "fy_year" in cols and "project_type" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_fy_proj ON {table_name}(fy_year, project_type)")
        if "state" in cols and "fy_year" in cols and "project_type" in cols:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_state_fy_proj ON {table_name}(state, fy_year, project_type)")
            
        conn.commit()
        print(f"  Success!")
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    start = time.time()
    db_files = glob.glob("*.db")
    for db_file in db_files:
        add_indexes_to_db(db_file)
    print(f"Finished adding indexes in {time.time() - start:.2f} seconds.")
