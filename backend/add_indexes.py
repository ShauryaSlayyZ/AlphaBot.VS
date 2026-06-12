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
        
        # Create indexes
        print(f"  Creating indexes on {table_name}...")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_department ON {table_name}(department)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_region ON {table_name}(region)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_record_date ON {table_name}(record_date)")
        
        # Also create composite and expression indexes for optimal search performance
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_dept_region ON {table_name}(department, region)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_dept_date ON {table_name}(department, record_date)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_region_date ON {table_name}(region, record_date)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_expr_year ON {table_name}(strftime('%Y', record_date))")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_expr_month ON {table_name}(strftime('%Y-%m', record_date))")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_expr_date ON {table_name}(DATE(record_date))")
        
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
