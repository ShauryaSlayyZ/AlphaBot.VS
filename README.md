# Alphabot v2.0 - Federated Analytics Engine 🚀

A modern, high-performance text-to-SQL analytics platform that queries 8 power plant databases in parallel using natural language.

![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Status](https://img.shields.io/badge/status-production--ready-green)

---

## 🌟 Features

- **Natural Language Queries** - Ask questions in plain English
- **Federated Architecture** - Query 8 SQLite databases in parallel
- **Real-time Results** - Sub-second response times with async processing
- **Smart Visualizations** - Automatic chart type selection based on data
- **AI-Powered Fallback** - Uses local LLM when needed
- **Beautiful UI** - Modern glassmorphic design with Tailwind CSS

---

## 📊 Architecture

```
User Query → Next.js Frontend → FastAPI Backend → 8 SQLite DBs (Parallel)
                    ↓                   ↓
              Client Parser      Federated Engine
                                       ↓
                              Aggregated Results
```

### Tech Stack

**Backend:**
- FastAPI (Python 3.13+)
- SQLite (8 federated databases)
- Asyncio (parallel execution)
- Pydantic (data validation)

**Frontend:**
- Next.js 16 (App Router)
- React 18
- Tailwind CSS
- TypeScript

---

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Node.js 24+
- npm

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd AlphaBot
```

2. **Setup Backend**
```bash
cd backend
pip install -r requirements.txt
python setup_databases.py  # Generates 8 databases with 50k records each
```

3. **Setup Frontend**
```bash
cd ../frontend
npm install
```

### Running the Application

**Terminal 1 - Backend:**
```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

**Access the application:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## 💡 Example Queries

Try these natural language queries:

- "What was total revenue in 2026?"
- "Show me profit breakdown by plant"
- "Revenue in sales department for 2026"
- "Graph revenue trends over time"
- "Headcount in digital department"
- "Compare expenses across all plants"

---

## 📁 Project Structure

```
AlphaBot/
├── backend/
│   ├── main.py                 # FastAPI app & federated engine
│   ├── setup_databases.py      # Database generator
│   ├── requirements.txt
│   └── *.db                    # 8 power plant databases
├── frontend/
│   ├── app/
│   │   ├── page.tsx           # Main dashboard
│   │   └── layout.tsx
│   ├── components/
│   │   ├── QueryInterface.tsx  # Input component
│   │   ├── ResultsDisplay.tsx  # Results container
│   │   └── DataChart.tsx       # Visualization engine
│   └── package.json
└── README.md
```

---

## 🎯 How It Works

### 1. Query Processing

```typescript
User types: "total revenue in sales for 2026"
    ↓
Frontend sends to: POST /api/query
    ↓
Backend creates blueprint:
{
  operation: "SUM",
  metrics: ["revenue"],
  filters: [{"column": "department", "value": "sales"}],
  timeframe: {"type": "year", "value": "2026"}
}
```

### 2. Federated Execution

```python
# Query all 8 databases in parallel
tasks = [query_db(plant) for plant in POWER_PLANTS]
results = await asyncio.gather(*tasks)

# Aggregate results
total_revenue = sum(r[0]['revenue'] for r in results)
```

### 3. Smart Visualization

The frontend automatically picks the best chart type:
- **Single value** → Large number card
- **Multiple metrics** → Horizontal bar chart
- **Time series** → Line graph
- **Categories** → Comparison bars

---

## 🗄️ Database Schema

Each of the 8 power plant databases contains:

| Column | Type | Description |
|--------|------|-------------|
| `record_date` | TIMESTAMP | When recorded |
| `department` | VARCHAR | sales, digital, marketing, etc. |
| `region` | VARCHAR | north, south, east, west, central |
| `revenue` | NUMERIC | Revenue in USD |
| `profit` | NUMERIC | Profit in USD |
| `expenses` | NUMERIC | Expenses in USD |
| `headcount` | INTEGER | Employee count |
| `salary` | NUMERIC | Payroll costs |
| `tax_liability` | NUMERIC | Tax amount |
| `asset_value` | NUMERIC | Asset valuation |
| `operating_cost` | NUMERIC | Operating expenses |
| `marketing_spend` | NUMERIC | Marketing budget |
| `customer_count` | INTEGER | Active customers |

**Total Records:** 400,000 (50k per plant)
**Date Range:** 2020-2027

---

## 🔧 API Endpoints

### POST `/api/query`

Submit a natural language query.

**Request:**
```json
{
  "raw_query": "total revenue in 2026",
  "blueprint": null
}
```

**Response:**
```json
{
  "status": "success",
  "results": [{"revenue": 1250000.50}],
  "sql_query": "SELECT SUM(revenue) as revenue FROM metrics WHERE strftime('%Y', record_date) = ?",
  "unit": "USD",
  "plants_queried": 8,
  "insights": {
    "summary": "Federated query successful.",
    "analysis": "Aggregated from 8 sources."
  },
  "metadata": {"backend_ms": 45}
}
```

### GET `/api/metadata`

Get available metrics and dimensions.

**Response:**
```json
{
  "metrics": ["revenue", "profit", "expenses", ...],
  "categoricals": {
    "department": ["sales", "digital", "marketing", ...],
    "region": ["north", "south", "east", "west", "central"]
  }
}
```

---

## 🎨 UI Features

- **Glassmorphic Design** - Modern blur effects and gradients
- **Responsive Layout** - Works on desktop and mobile
- **Live Examples** - Click example queries to populate input
- **Real-time Feedback** - Loading states and error handling
- **Data Tables** - Raw data view with formatting
- **SQL Display** - See generated queries

---

## 📈 Performance

- **Backend Response:** 40-80ms (parallel DB queries)
- **8 Database Queries:** Executed in parallel via asyncio
- **50k Records per DB:** 400k total records
- **No LLM Overhead:** Client-side parsing bypasses AI when possible

---

## 🚧 Roadmap

### Priority 1: Production Deployment
- [ ] Docker containerization
- [ ] API authentication
- [ ] Deploy to Vercel (frontend) + Cloud Run (backend)

### Priority 2: Advanced Features
- [ ] PostgreSQL migration
- [ ] Redis caching layer
- [ ] User authentication
- [ ] Query history

### Priority 3: Enhancements
- [ ] More chart types (heatmaps, maps)
- [ ] Export to CSV/Excel
- [ ] Scheduled reports
- [ ] Real-time data streaming

---

## 🐛 Known Issues

- **LLM Fallback:** Requires Ollama running locally (optional)
- **SQLite Limits:** Not suitable for millions of rows
- **No Authentication:** API is currently open

---

## 📝 Development Notes

### Adding New Metrics

1. Update database schema in `setup_databases.py`
2. Regenerate databases: `python setup_databases.py`
3. Restart backend to reinitialize metadata registry

### Testing

```bash
# Backend tests
cd backend
pytest test_main.py

# Test accuracy
python run_api_test_harness.py
```

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🤝 Contributing

Contributions welcome! Please read CONTRIBUTING.md for guidelines.

---

## 📧 Support

For issues and questions:
- GitHub Issues: [Create an issue]
- Documentation: See HANDOVER_DOCUMENT.md

---

**Built with ❤️ for high-performance analytics**
