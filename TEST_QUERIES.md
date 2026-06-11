# Alphabot v2.0 - Test Queries Guide 🧪

Based on actual database analysis of 400,000 records across 8 power plants.

---

## 📊 Database Stats

- **Total Records:** 400,000 (50k per plant)
- **Date Range:** 2020-2027
- **8 Plants:** diablo_canyon, three_mile_island, palo_verde, grand_gulf, vogtle, hinkley_point, kashiwazaki, darlington
- **8 Departments:** sales, digital, marketing, hr, engineering, finance, support, operations
- **5 Regions:** north, south, east, west, central

---

## ✅ Level 1: Basic Queries (Start Here)

### Simple Aggregations
These return a single number across all 8 plants.

```
total revenue in 2026
```
**Expected:** ~$58.8M (aggregated from all 8 plants)

```
total profit in 2026
```
**Expected:** ~$10.2M (all plants combined)

```
total headcount in 2026
```
**Expected:** ~4.5M people (sum across all plants)

```
total expenses in 2026
```
**Expected:** ~$48.5M

```
total customer count in 2026
```
**Expected:** ~20M customers

---

## 📍 Level 2: Filtered Queries

### Filter by Department
```
revenue in sales department for 2026
```
**Expected:** ~$7.4M from sales department across all plants

```
profit in digital for 2026
```
**Expected:** ~$1.6M from digital department

```
headcount in engineering for 2026
```
**Expected:** ~563k engineers across all plants

### Filter by Region
```
profit in north region for 2026
```
**Expected:** ~$2M from northern region

```
revenue in south region for 2026
```
**Expected:** ~$11.8M from southern region

```
expenses in east for 2026
```
**Expected:** ~$9.7M

### Filter by Plant
```
revenue at diablo_canyon plant for 2026
```
**Expected:** ~$7.3M (single plant only)

```
profit at grand_gulf for 2026
```
**Expected:** ~$1.3M

### Combine Filters
```
revenue in sales department in north region for 2026
```
**Expected:** Filtered by both department AND region

```
profit in digital in east for 2026
```
**Expected:** Digital department in eastern region only

---

## 🔥 Level 3: Breakdown Queries

These return multiple rows for comparison.

### Breakdown by Department
```
revenue breakdown by department for 2026
```
**Expected Result:**
- operations: $X
- marketing: $Y
- engineering: $Z
- ... (8 departments total)

```
profit breakdown by department for 2026
```
**Expected:** Bar chart comparing all departments

### Breakdown by Region
```
profit breakdown by region for 2026
```
**Expected Result:**
- east: ~$2.1M
- south: ~$2.1M
- north: ~$2M
- central: ~$2M
- west: ~$2M

```
expenses breakdown by region for 2026
```
**Expected:** 5 regions compared

### Breakdown by Plant
```
revenue breakdown by plant for 2026
```
**Expected Result:**
- diablo_canyon: $7.3M
- three_mile_island: $7.3M
- palo_verde: $7.3M
- ... (8 plants)

```
headcount breakdown by plant for 2026
```
**Expected:** Employee count per plant

---

## 🎯 Level 4: Complex Multi-Filter Queries

### Department + Region
```
revenue in sales in north for 2026
```
**Expected:** Sales department, northern region only

```
profit in digital in south region for 2026
```
**Expected:** Specific department + region intersection

### Department + Region + Breakdown
```
show all metrics for sales in north for 2026
```
**Expected:** All 10 metrics displayed as bars:
- revenue
- profit
- expenses
- headcount
- salary
- tax_liability
- asset_value
- operating_cost
- marketing_spend
- customer_count

---

## 📈 Level 5: Time-Based Queries

### Specific Years
```
total revenue in 2025
```
**Expected:** Different from 2026

```
profit in 2024
```
**Expected:** Historical data

```
revenue in 2027
```
**Expected:** Most recent data

### Year Ranges (if supported)
```
revenue from 2024 to 2026
```
**Expected:** Multi-year aggregation

---

## 🧩 Level 6: Edge Cases & Special Queries

### All Available Data
```
total revenue
```
**Expected:** Everything (2020-2027)

```
total profit
```
**Expected:** No year filter = all years

### Specific Metric Types
```
total salary in 2026
```
**Expected:** Payroll costs

```
total marketing spend for 2026
```
**Expected:** Marketing budget

```
total asset value in 2026
```
**Expected:** Asset valuations

```
total tax liability for 2026
```
**Expected:** Tax amounts

### Department Variations
```
revenue in operations for 2026
```
**Expected:** Operations department

```
profit in hr department for 2026
```
**Expected:** HR department

```
headcount in support for 2026
```
**Expected:** Support team size

---

## 🎨 Visual Test Scenarios

### Single Value Display
Any query returning one number:
```
total revenue in 2026
```
**UI:** Large number card

### Bar Chart (Multiple Metrics)
```
show all metrics for sales in north for 2026
```
**UI:** Horizontal bars showing 10 metrics

### Comparison Bars (Multiple Categories)
```
revenue breakdown by plant for 2026
```
**UI:** 8 bars comparing plants

```
profit breakdown by region for 2026
```
**UI:** 5 bars comparing regions

---

## 🚀 Performance Test Queries

### Fast Queries (Should be <50ms)
```
total revenue in 2026
```
Simple aggregation, year filter only

### Medium Queries (50-100ms)
```
revenue breakdown by plant for 2026
```
Grouping by plant with year filter

### Complex Queries (100-200ms)
```
revenue in sales in north for 2026
```
Multiple filters + aggregation

---

## ⚠️ Expected Behaviors

### Automatic Plant Aggregation
When NO plant is specified:
```
total revenue in 2026
```
→ Queries ALL 8 plants in parallel and sums results

### Single Plant Query
When plant IS specified:
```
revenue at diablo_canyon for 2026
```
→ Queries ONLY that plant's database

### Default Metric
If no metric specified with department+region filters:
```
show metrics for sales in north for 2026
```
→ Returns ALL 10 metrics as breakdown

---

## 📝 Copy-Paste Test Suite

Quick test set (copy these one by one):

```
total revenue in 2026
total profit in 2026
revenue in sales for 2026
profit in north region for 2026
revenue breakdown by plant for 2026
profit breakdown by department for 2026
revenue in sales in north for 2026
show all metrics for digital in east for 2026
headcount breakdown by region for 2026
total expenses in 2026
```

---

## 🔍 Verification Checklist

For each query, verify:
- [ ] Response time shown (should be <200ms)
- [ ] Correct number of plants queried (8 or 1)
- [ ] Unit displayed correctly (USD or Units)
- [ ] Chart type appropriate for data
- [ ] SQL query shown in results
- [ ] Data table populated correctly

---

## 💡 Tips for Testing

1. **Start Simple:** Begin with single aggregations
2. **Add Complexity:** Gradually add filters
3. **Test Breakdowns:** Verify multiple-row results
4. **Check Performance:** All queries should be fast
5. **Verify Accuracy:** Numbers should make sense
6. **Test Edge Cases:** Try unusual combinations
7. **Check UI:** Ensure proper chart rendering

---

## 🎯 Expected Value Ranges

Based on actual database:

| Metric | Typical 2026 Value (All Plants) |
|--------|----------------------------------|
| Revenue | $50M - $60M |
| Profit | $9M - $11M |
| Expenses | $45M - $50M |
| Headcount | 4M - 5M people |
| Salary | $250M - $300M |
| Tax Liability | $2M - $3M |
| Asset Value | $150M - $200M |
| Operating Cost | $40M - $45M |
| Marketing Spend | $2.5M - $3M |
| Customer Count | 18M - 22M |

Single plant values = ~1/8 of above

---

**Happy Testing! 🚀**
