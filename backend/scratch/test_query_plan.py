import sqlite3
import time

def run_explain():
    conn = sqlite3.connect("diablo_canyon.db")
    cursor = conn.cursor()
    
    # Find the metrics table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
    table_name = cursor.fetchone()[0]
    
    print("Creating temporary composite index...")
    cursor.execute(f"DROP INDEX IF EXISTS idx_{table_name}_dept_date_test")
    cursor.execute(f"CREATE INDEX idx_{table_name}_dept_date_test ON {table_name}(department, record_date)")
    conn.commit()
    
    print("\n--- Explain Query Plan (strftime IN + department) ---")
    cursor.execute(f"EXPLAIN QUERY PLAN SELECT SUM(revenue) FROM {table_name} WHERE department = 'sales' AND strftime('%Y', record_date) IN ('2023', '2024')")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- Explain Query Plan (Range-based OR + department) ---")
    cursor.execute(f"EXPLAIN QUERY PLAN SELECT SUM(revenue) FROM {table_name} WHERE department = 'sales' AND ((record_date >= '2023-01-01 00:00:00' AND record_date < '2024-01-01 00:00:00') OR (record_date >= '2024-01-01 00:00:00' AND record_date < '2025-01-01 00:00:00'))")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- Execution Time Benchmark (100 runs) ---")
    
    start = time.perf_counter()
    for _ in range(100):
        cursor.execute(f"SELECT SUM(revenue) FROM {table_name} WHERE department = 'sales' AND strftime('%Y', record_date) IN ('2023', '2024')")
        _ = cursor.fetchone()
    time_strftime = time.perf_counter() - start
    print(f"strftime query time: {time_strftime * 1000:.2f} ms")
    
    start = time.perf_counter()
    for _ in range(100):
        cursor.execute(f"SELECT SUM(revenue) FROM {table_name} WHERE department = 'sales' AND ((record_date >= '2023-01-01 00:00:00' AND record_date < '2024-01-01 00:00:00') OR (record_date >= '2024-01-01 00:00:00' AND record_date < '2025-01-01 00:00:00'))")
        _ = cursor.fetchone()
    time_range = time.perf_counter() - start
    print(f"Range-based query time: {time_range * 1000:.2f} ms")
    
    print(f"\nSpeedup: {time_strftime / time_range:.2f}x faster!")
    
    # Cleanup
    cursor.execute(f"DROP INDEX IF EXISTS idx_{table_name}_dept_date_test")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_explain()
