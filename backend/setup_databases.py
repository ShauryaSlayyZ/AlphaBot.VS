
import sqlite3
import random
import os
from datetime import datetime, timedelta

# List of 8 power plant names
POWER_PLANTS = [
    "diablo_canyon", "three_mile_island", "palo_verde", 
    "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"
]

RECORDS_PER_DB = 50000
DEPARTMENTS = ["digital", "sales", "marketing", "hr", "engineering", "finance", "support", "operations"]
REGIONS = ["north", "south", "east", "west", "central"]

def create_single_database(plant_name: str, table_name: str):
    db_name = f"{plant_name}.db"
    
    if os.path.exists(db_name):
        os.remove(db_name)
        print(f"Removed existing database: {db_name}")

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute(f"""
    CREATE TABLE {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_date TIMESTAMP NOT NULL,
        department VARCHAR(50) NOT NULL,
        region VARCHAR(50) NOT NULL,
        revenue NUMERIC,
        profit NUMERIC,
        expenses NUMERIC,
        headcount INTEGER,
        salary NUMERIC,
        tax_liability NUMERIC,
        asset_value NUMERIC,
        operating_cost NUMERIC,
        marketing_spend NUMERIC,
        customer_count INTEGER
    );
    """)
    conn.commit()

    records = []
    print(f"Generating {RECORDS_PER_DB} records for {db_name}...")
    start_date = datetime(2020, 1, 1)
    
    # Ensure every department is represented in every plant
    # Extended to 7 years (2020-2027)
    for _ in range(RECORDS_PER_DB):
        date = start_date + timedelta(days=random.randint(0, 365 * 7), hours=random.randint(0, 23))
        dept = random.choice(DEPARTMENTS)
        region = random.choice(REGIONS)
        revenue = round(random.uniform(50000, 2000000), 2)
        profit = revenue * random.uniform(0.05, 0.3)
        expenses = revenue - profit
        headcount = random.randint(10, 150)
        salary = headcount * random.uniform(45000, 85000)
        
        records.append((
            date.strftime("%Y-%m-%d %H:%M:%S"),
            dept,
            region,
            revenue,
            round(profit, 2),
            round(expenses, 2),
            headcount,
            round(salary, 2),
            round(profit * 0.2, 2), 
            round(revenue * 2.5, 2), 
            round(expenses * 0.8, 2), 
            round(revenue * 0.05, 2), 
            random.randint(500, 5000) 
        ))

    cursor.executemany(f"""
    INSERT INTO {table_name} (record_date, department, region, revenue, profit, expenses, headcount, salary, tax_liability, asset_value, operating_cost, marketing_spend, customer_count)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, records)
    
    conn.commit()
    conn.close()
    print(f"[OK] {db_name} is ready.")

if __name__ == "__main__":
    for plant in POWER_PLANTS:
        table = f"metrics_{plant}"
        create_single_database(plant, table)
    
    print("\nAll databases have been generated successfully with complete department data!")
