# Alphabot v2.0 - Quick Start Guide ⚡

Get Alphabot running in 60 seconds!

---

## 🎯 One-Command Startup (Windows)

```powershell
.\start.ps1
```

This script will:
1. Create databases if needed (400k records)
2. Start the backend server on port 8000
3. Start the frontend on port 3000

---

## 🔧 Manual Startup

### Step 1: Start Backend

Open a terminal:
```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

You should see:
```
✅ Singleton Registry Initialized. Metrics: ['revenue', 'profit', ...]
INFO: Uvicorn running on http://127.0.0.1:8000
```

### Step 2: Start Frontend

Open another terminal:
```bash
cd frontend
npm run dev
```

You should see:
```
▲ Next.js 16.2.7
- Local: http://localhost:3000
✓ Ready in 688ms
```

---

## 🌐 Access the Application

1. **Open your browser:** http://localhost:3000

2. **Try example queries:**
   - "What was total revenue in 2026?"
   - "Show me profit breakdown by plant"
   - "Revenue in sales department"

3. **See the magic happen:**
   - Query gets parsed
   - 8 databases queried in parallel
   - Results aggregated and visualized

---

## 📊 What You Can Query

### Available Metrics
- `revenue` - Total income
- `profit` - Net earnings
- `expenses` - Total costs
- `headcount` - Employee count
- `salary` - Payroll costs
- `tax_liability` - Tax amounts
- `asset_value` - Asset valuations
- `operating_cost` - Operational expenses
- `marketing_spend` - Marketing budget
- `customer_count` - Active customers

### Available Filters
- **Departments:** sales, digital, marketing, hr, engineering, finance, support, operations
- **Regions:** north, south, east, west, central
- **Plants:** diablo_canyon, three_mile_island, palo_verde, grand_gulf, vogtle, hinkley_point, kashiwazaki, darlington
- **Time:** 2020-2027

### Query Examples

**Simple Aggregation:**
```
"total revenue"
"average profit in 2026"
"sum of expenses"
```

**Filtered Queries:**
```
"revenue in sales department"
"profit in north region"
"headcount at diablo_canyon plant"
```

**Breakdowns:**
```
"revenue breakdown by plant"
"profit by department"
"expenses by region"
```

**Time Series:**
```
"graph revenue over time"
"show profit trends"
"revenue trend in 2026"
```

**Complex Queries:**
```
"revenue in sales for 2026"
"profit breakdown by plant in digital department"
"headcount in north region for marketing"
```

---

## 🎨 UI Features

### Dashboard Components

1. **Query Input**
   - Type natural language queries
   - Click example queries
   - Real-time processing

2. **AI Insights**
   - Summary of what was found
   - Analysis details

3. **Visual Results**
   - Auto-selected chart type
   - Responsive design
   - Color-coded data

4. **Metadata Cards**
   - Plants queried
   - Response time
   - Unit type

5. **SQL Display**
   - See generated query
   - Understand the logic

6. **Raw Data Table**
   - Complete results
   - Formatted numbers

---

## 🔍 Troubleshooting

### Backend won't start

**Error:** `uvicorn: The term 'uvicorn' is not recognized`

**Fix:**
```bash
pip install -r requirements.txt
```

### No databases found

**Error:** `FATAL: Database diablo_canyon.db not found`

**Fix:**
```bash
cd backend
python setup_databases.py
```

### Frontend build errors

**Error:** Module not found

**Fix:**
```bash
cd frontend
npm install
```

### Port already in use

**Error:** `Port 3000 is already in use`

**Fix:**
```bash
# Kill the process using the port
# Windows:
netstat -ano | findstr :3000
taskkill /PID <PID> /F

# Or use a different port:
npm run dev -- -p 3001
```

### CORS errors

**Error:** `Access-Control-Allow-Origin`

**Fix:** Backend already has CORS enabled. Make sure:
- Backend is running on http://localhost:8000
- Frontend is running on http://localhost:3000
- Both services are accessible

---

## 🧪 Testing the API

### Using curl

```bash
# Health check
curl http://localhost:8000/

# Get metadata
curl http://localhost:8000/api/metadata

# Query
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"raw_query": "total revenue", "blueprint": null}'
```

### Using Browser

Navigate to: http://localhost:8000/docs

This opens the interactive Swagger UI where you can test all endpoints.

---

## 📈 Performance Tips

1. **Specific Queries:** Filter by plant/department/region for faster results
2. **Avoid Wide Date Ranges:** Narrow timeframes = faster queries
3. **Use Breakdowns Wisely:** Grouping by categories adds processing time

---

## 🎓 Learning Path

1. **Start Simple:** Try "total revenue"
2. **Add Filters:** "revenue in sales"
3. **Add Time:** "revenue in 2026"
4. **Try Breakdowns:** "revenue by plant"
5. **Go Complex:** "profit breakdown by plant in sales for 2026"

---

## 🚀 Next Steps

Once comfortable with basic queries:

1. **Explore the Code**
   - `backend/main.py` - Federated engine logic
   - `frontend/app/page.tsx` - Main UI
   - `frontend/components/` - UI components

2. **Customize**
   - Add new metrics
   - Change visualization styles
   - Modify query parsing

3. **Deploy**
   - See README.md for deployment guides
   - Docker setup coming soon

---

## 💬 Getting Help

- Read the full **README.md** for detailed information
- Check **HANDOVER_DOCUMENT.md** for architecture details
- Review **handover_report.md** for technical specs

---

**🎉 You're ready to explore your data with natural language!**
