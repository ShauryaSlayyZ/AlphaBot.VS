
import sqlite3
import json
import os

# List of 8 power plant names
POWER_PLANTS = [
    "diablo_canyon", "three_mile_island", "palo_verde", 
    "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"
]
REPORT_FILE = "ground_truth.json"

def calculate_ground_truth():
    """
    Connects to all databases, runs a series of hardcoded SQL queries,
    aggregates the results, and saves them to a JSON file.
    """
    
    report = {
        "total_profit_2025": 0.0,
        "total_revenue_north_2024": 0.0,
        "total_headcount_digital": 0,
        "total_marketing_spend_finance_2023": 0.0
    }

    print("--- 🛡️  Generating Ground Truth Report ---")

    for plant in POWER_PLANTS:
        db_file = f"{plant}.db"
        
        if not os.path.exists(db_file):
            print(f"⚠️  Database {db_file} not found. Skipping.")
            continue
        
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Dynamically find table name
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'metrics_%'")
        table_name = cursor.fetchone()[0]
        
        print(f"Processing {db_file} ({table_name})...")

        # Test Case 1: Total Profit for FY2025
        cursor.execute(f"SELECT SUM(profit) FROM {table_name} WHERE strftime('%Y', record_date) = '2025'")
        result = cursor.fetchone()[0]
        if result: report["total_profit_2025"] += result

        # Test Case 2: Total Revenue for North in FY2024
        cursor.execute(f"SELECT SUM(revenue) FROM {table_name} WHERE region = 'north' AND strftime('%Y', record_date) = '2024'")
        result = cursor.fetchone()[0]
        if result: report["total_revenue_north_2024"] += result
        
        # Test Case 3: Total Headcount for Digital department (all time)
        cursor.execute(f"SELECT SUM(headcount) FROM {table_name} WHERE department = 'digital'")
        result = cursor.fetchone()[0]
        if result: report["total_headcount_digital"] += result

        # Test Case 4: Total Marketing Spend for Finance in FY2023
        cursor.execute(f"SELECT SUM(marketing_spend) FROM {table_name} WHERE department = 'finance' AND strftime('%Y', record_date) = '2023'")
        result = cursor.fetchone()[0]
        if result: report["total_marketing_spend_finance_2023"] += result
        
        conn.close()

    # Round floats for consistent comparison
    for key, value in report.items():
        if isinstance(value, float):
            report[key] = round(value, 2)
            
    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)

    print("\n--- ✅ Ground Truth Report Generated ---")
    print(json.dumps(report, indent=2))
    print(f"\nReport saved to {REPORT_FILE}")


if __name__ == "__main__":
    calculate_ground_truth()
