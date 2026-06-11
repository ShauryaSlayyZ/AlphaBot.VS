import sqlite3
from datetime import datetime

# Connect to one of the databases
conn = sqlite3.connect('diablo_canyon.db')
cursor = conn.cursor()

print("=" * 80)
print("DATABASE ANALYSIS - Alphabot v2.0")
print("=" * 80)

# 1. Total records
cursor.execute("SELECT COUNT(*) FROM metrics_diablo_canyon")
total = cursor.fetchone()[0]
print(f"\n📊 Total Records: {total:,}")

# 2. Date range
cursor.execute("SELECT MIN(record_date), MAX(record_date) FROM metrics_diablo_canyon")
min_date, max_date = cursor.fetchone()
print(f"📅 Date Range: {min_date} to {max_date}")

# 3. Departments
cursor.execute("SELECT department, COUNT(*) as count FROM metrics_diablo_canyon GROUP BY department ORDER BY count DESC")
print("\n🏢 Departments:")
for dept, count in cursor.fetchall():
    print(f"   • {dept}: {count:,} records")

# 4. Regions
cursor.execute("SELECT region, COUNT(*) as count FROM metrics_diablo_canyon GROUP BY region ORDER BY count DESC")
print("\n🗺️  Regions:")
for region, count in cursor.fetchall():
    print(f"   • {region}: {count:,} records")

# 5. Sample metrics for 2026
cursor.execute("""
    SELECT 
        SUM(revenue) as total_revenue,
        SUM(profit) as total_profit,
        SUM(expenses) as total_expenses,
        SUM(headcount) as total_headcount
    FROM metrics_diablo_canyon 
    WHERE strftime('%Y', record_date) = '2026'
""")
revenue, profit, expenses, headcount = cursor.fetchone()
print("\n💰 2026 Totals (Single Plant - Diablo Canyon):")
print(f"   • Revenue: ${revenue:,.2f}")
print(f"   • Profit: ${profit:,.2f}")
print(f"   • Expenses: ${expenses:,.2f}")
print(f"   • Headcount: {headcount:,}")

# 6. Sample by department for 2026
cursor.execute("""
    SELECT 
        department,
        SUM(revenue) as revenue
    FROM metrics_diablo_canyon 
    WHERE strftime('%Y', record_date) = '2026'
    GROUP BY department
    ORDER BY revenue DESC
    LIMIT 5
""")
print("\n📈 Top 5 Departments by Revenue (2026):")
for dept, rev in cursor.fetchall():
    print(f"   • {dept}: ${rev:,.2f}")

# 7. Sample by region
cursor.execute("""
    SELECT 
        region,
        SUM(profit) as profit
    FROM metrics_diablo_canyon 
    WHERE strftime('%Y', record_date) = '2026'
    GROUP BY region
    ORDER BY profit DESC
""")
print("\n🌎 Profit by Region (2026):")
for region, prof in cursor.fetchall():
    print(f"   • {region}: ${prof:,.2f}")

# 8. Sample monthly trend
cursor.execute("""
    SELECT 
        strftime('%Y-%m', record_date) as month,
        SUM(revenue) as revenue
    FROM metrics_diablo_canyon 
    WHERE strftime('%Y', record_date) = '2026'
    GROUP BY month
    ORDER BY month
    LIMIT 6
""")
print("\n📊 Monthly Revenue Trend (First 6 months of 2026):")
for month, rev in cursor.fetchall():
    print(f"   • {month}: ${rev:,.2f}")

conn.close()

print("\n" + "=" * 80)
print("RECOMMENDED TEST QUERIES")
print("=" * 80)

queries = [
    # Simple aggregations
    ("Simple Total", "total revenue in 2026"),
    ("Single Metric", "total profit in 2026"),
    ("Count Metric", "total headcount in 2026"),
    
    # Filtered queries
    ("Department Filter", "revenue in sales department for 2026"),
    ("Region Filter", "profit in north region for 2026"),
    ("Dept + Year", "expenses in digital for 2026"),
    
    # Breakdowns
    ("By Department", "revenue breakdown by department for 2026"),
    ("By Region", "profit breakdown by region for 2026"),
    ("By Plant", "revenue breakdown by plant for 2026"),
    
    # Complex filters
    ("Dept + Region", "revenue in sales department in north region for 2026"),
    ("Plant Specific", "profit at diablo_canyon plant for 2026"),
    
    # Multiple metrics
    ("All Metrics", "show all metrics for sales in north for 2026"),
    
    # Trends (if supported)
    ("Time Trend", "graph revenue over time in 2026"),
    ("Monthly Trend", "show revenue trend for 2026"),
]

print("\n✅ BASIC QUERIES (Start Here):")
for i, (label, query) in enumerate(queries[:6], 1):
    print(f"{i}. {query}")
    print(f"   [{label}]")

print("\n🔥 ADVANCED QUERIES:")
for i, (label, query) in enumerate(queries[6:], 7):
    print(f"{i}. {query}")
    print(f"   [{label}]")

print("\n💡 TIPS:")
print("   • All 8 plants will be queried automatically (unless you specify a plant)")
print("   • Try different years: 2020-2027")
print("   • Mix and match: departments, regions, metrics")
print("   • The system will aggregate across all 8 plants for total values")

print("\n" + "=" * 80)
