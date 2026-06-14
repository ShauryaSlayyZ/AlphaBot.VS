import sqlite3

conn = sqlite3.connect("backend/palo_verde.db")
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
tables = c.fetchall()
print("Tables:", tables)

if tables:
    table_name = tables[0][0]
    c.execute(f"SELECT DISTINCT fy_year FROM {table_name}")
    print("Years:", c.fetchall())
    
    c.execute(f"SELECT COUNT(*), strftime('%Y-%m', record_date) FROM {table_name} WHERE fy_year=2026 GROUP BY strftime('%Y-%m', record_date)")
    print("2026 months:", c.fetchall())

conn.close()
