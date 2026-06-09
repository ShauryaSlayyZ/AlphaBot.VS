
import sqlite3
import random
from datetime import datetime

DB_NAME = "market_intel.db"
TABLE_NAME = "competitor_metrics"
NUM_ROWS = 50000 # Smaller dataset for external intelligence

COMPETITORS = ["GlobalCorp", "TechNova", "EcoSystems", "DataPrime", "Apex Solutions"]
REGIONS = ["north", "south", "east", "west", "central"]

def create_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_name VARCHAR(100) NOT NULL,
        region VARCHAR(50) NOT NULL,
        market_share NUMERIC,
        estimated_revenue NUMERIC,
        year INTEGER NOT NULL
    );
    """)
    conn.commit()
    
    records = []
    print(f"🚀 Generating {NUM_ROWS} market intelligence records...")
    for _ in range(NUM_ROWS):
        comp = random.choice(COMPETITORS)
        reg = random.choice(REGIONS)
        share = round(random.uniform(1.0, 30.0), 2)
        rev = round(random.uniform(1000000, 100000000), 2)
        year = random.randint(2020, 2026)
        records.append((comp, reg, share, rev, year))

    cursor.executemany(f"INSERT INTO {TABLE_NAME} (competitor_name, region, market_share, estimated_revenue, year) VALUES (?, ?, ?, ?, ?);", records)
    conn.commit()
    conn.close()
    print(f"✅ {DB_NAME} is ready.")

if __name__ == "__main__":
    create_database()
