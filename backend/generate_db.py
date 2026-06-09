
import sqlite3
import random
from datetime import datetime, timedelta

# --- Configuration ---
DB_NAME = "benchmark_test.db"
TABLE_NAME = "corporate_metrics"
NUM_ROWS = 250000

DEPARTMENTS = ["digital", "marketing", "tech", "hr", "sales", "product", "finance", "engineering", "support", "operations"]
REGIONS = ["north", "south", "east", "west", "central"]

# The 10 requested metrics for complexity
METRICS = [
    "revenue", "profit", "expenses", "headcount", "salary",
    "tax_liability", "asset_value", "operating_cost", "marketing_spend", "customer_count"
]

# --- Main Script ---

def generate_random_date(start_date, end_date):
    time_between_dates = end_date - start_date
    days_between_dates = time_between_dates.days
    random_number_of_days = random.randrange(days_between_dates)
    return start_date + timedelta(days=random_number_of_days)

def get_fiscal_year(date_obj):
    year = date_obj.year
    return f"FY{year + 1}" if date_obj.month >= 7 else f"FY{year}"

def create_database_and_table(conn):
    cursor = conn.cursor()
    
    # Dynamically build the CREATE TABLE statement with the 10 metrics
    columns_sql = ",\n        ".join([f"{m} NUMERIC" for m in METRICS])
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_date DATETIME NOT NULL,
        fiscal_year VARCHAR(10) NOT NULL,
        department VARCHAR(50) NOT NULL,
        region VARCHAR(50) NOT NULL,
        {columns_sql}
    );
    """)
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_fiscal_year ON {TABLE_NAME} (fiscal_year);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_department ON {TABLE_NAME} (department);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_region ON {TABLE_NAME} (region);")
    conn.commit()
    print("✅ Database schema with 10 metrics is ready.")

def generate_and_insert_data(conn):
    cursor = conn.cursor()
    records_to_insert = []
    start_date, end_date = datetime(2020, 1, 1), datetime(2026, 12, 31)

    print(f"🚀 Generating {NUM_ROWS} complex mock records...")

    for _ in range(NUM_ROWS):
        record_date = generate_random_date(start_date, end_date)
        fiscal_year = get_fiscal_year(record_date)
        dept, reg = random.choice(DEPARTMENTS), random.choice(REGIONS)
        
        # Base values for realistic correlations
        base_revenue = random.uniform(1000.0, 500000.0)
        
        # Generate the 10 metric values
        metrics_values = [
            round(base_revenue, 2), # revenue
            round(base_revenue * 0.2, 2), # profit
            round(base_revenue * 0.8, 2), # expenses
            random.randint(5, 100), # headcount
            round(base_revenue * 0.3, 2), # salary
            round(base_revenue * 0.05, 2), # tax
            round(base_revenue * 5.0, 2), # asset_value
            round(base_revenue * 0.4, 2), # operating_cost
            round(base_revenue * 0.15, 2), # marketing_spend
            random.randint(10, 1000) # customer_count
        ]

        records_to_insert.append(
            (record_date, fiscal_year, dept, reg, *metrics_values)
        )

    print("💾 Inserting records into database...")
    placeholders = ", ".join(["?"] * (4 + len(METRICS)))
    cursor.executemany(f"INSERT INTO {TABLE_NAME} (record_date, fiscal_year, department, region, {', '.join(METRICS)}) VALUES ({placeholders});", records_to_insert)
    conn.commit()
    print(f"✅ Successfully inserted {NUM_ROWS} records.")

def main():
    try:
        conn = sqlite3.connect(DB_NAME)
        create_database_and_table(conn)
        generate_and_insert_data(conn)
    except sqlite3.Error as e: print(f"❌ Error: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()
