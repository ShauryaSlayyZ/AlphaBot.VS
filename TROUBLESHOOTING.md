# Troubleshooting Guide 🔧

## What's Not Working?

Please tell me specifically:

### 1. **Frontend Issues?**
- [ ] Can't access http://localhost:3000
- [ ] Page loads but is blank
- [ ] Query input doesn't work
- [ ] Charts not displaying
- [ ] Error messages showing

### 2. **Query Issues?**
- [ ] Queries return no results
- [ ] Queries timeout
- [ ] Wrong data displayed
- [ ] Charts show but data is wrong

### 3. **Ollama Issues?**
- [ ] Natural language doesn't work
- [ ] Only structured queries work
- [ ] Slow response times

---

## Quick Diagnostics

### Check 1: Are servers running?

**Backend (port 8000):**
```powershell
curl http://localhost:8000/
```
Expected: `{"status":"online"}`

**Frontend (port 3000):**
Open: http://localhost:3000  
Expected: See the Alphabot dashboard

**Ollama (port 11434):**
```powershell
curl http://localhost:11434/api/tags
```
Expected: JSON with models list

---

### Check 2: Test a simple query

Open http://localhost:3000 and type:
```
total revenue in 2026
```

**If it works:**
- ✅ Backend is working
- ✅ Database is working
- ✅ Charts are working

**If it doesn't work:**
Tell me what you see:
- Error message?
- Blank screen?
- Loading forever?
- Something else?

---

### Check 3: Browser Console

1. Open http://localhost:3000
2. Press F12 (Developer Tools)
3. Click "Console" tab
4. Try a query
5. Look for red error messages

**Common errors:**
- `CORS error` → Backend not running
- `Network error` → Backend crashed
- `Chart error` → Chart.js issue
- `404 error` → Wrong API endpoint

---

## Common Issues & Fixes

### Issue 1: "Cannot access http://localhost:3000"

**Fix:**
```powershell
cd frontend
npm run dev
```

Wait for: `✓ Ready in ...ms`  
Then try again.

---

### Issue 2: "Page loads but queries don't work"

**Fix:**
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```

Wait for: `Application startup complete`  
Then try again.

---

### Issue 3: "Charts not showing, just raw data"

**Possible causes:**
1. Chart.js didn't install
2. Frontend needs rebuild

**Fix:**
```powershell
cd frontend
npm install chart.js react-chartjs-2
# Restart the dev server (Ctrl+C then npm run dev)
```

---

### Issue 4: "Queries timeout or hang"

**Causes:**
- Databases not generated
- Ollama taking too long
- Query too complex

**Fix:**
```powershell
cd backend
python setup_databases.py
```

If Ollama is slow, try structured queries first:
```
total revenue in 2026
```

---

### Issue 5: "Natural language doesn't work"

**Check if Ollama is running:**
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

Keep this terminal open.

Then restart backend:
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```

---

### Issue 6: "Wrong data or charts"

**Symptoms:**
- All numbers are the same
- Charts don't match query
- Results don't make sense

**Causes:**
- Query parsing issue
- Backend defaulting incorrectly

**Debug:**
1. Check SQL query shown below chart
2. Look at "Plants Queried" number
3. Try structured query instead

---

## Step-by-Step Restart

If nothing works, do a full restart:

### Step 1: Stop everything
Press Ctrl+C in all terminals

### Step 2: Start Ollama
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```
Leave this running.

### Step 3: Start Backend
New terminal:
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```
Wait for: `Application startup complete`

### Step 4: Start Frontend
New terminal:
```powershell
cd frontend
npm run dev
```
Wait for: `✓ Ready in ...ms`

### Step 5: Test
Open: http://localhost:3000  
Type: `total revenue in 2026`  
Click: "Run Query"

---

## Still Not Working?

Tell me:
1. **What you see** (screenshot or description)
2. **What you expected**
3. **What query you tried**
4. **Any error messages**

I'll help you fix it!

---

## Working Queries to Test

### Test 1: Structured (Should always work)
```
total revenue in 2026
```

### Test 2: With filter
```
revenue in sales for 2026
```

### Test 3: Breakdown
```
revenue breakdown by plant for 2026
```

### Test 4: Natural language (Needs Ollama)
```
how much money did we make in 2026?
```

Try these in order. Tell me which one fails!
