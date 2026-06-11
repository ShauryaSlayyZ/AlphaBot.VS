# Alphabot v2.0 Startup Script
Write-Host "🚀 Starting Alphabot v2.0..." -ForegroundColor Cyan
Write-Host ""

# Check if databases exist
if (-not (Test-Path "backend\diablo_canyon.db")) {
    Write-Host "⚙️  Setting up databases..." -ForegroundColor Yellow
    Push-Location backend
    python setup_databases.py
    Pop-Location
    Write-Host "✅ Databases created!" -ForegroundColor Green
    Write-Host ""
}

# Start Backend
Write-Host "🔧 Starting Backend Server (Port 8000)..." -ForegroundColor Magenta
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; python -m uvicorn main:app --reload --port 8000"

# Wait a moment for backend to start
Start-Sleep -Seconds 3

# Start Frontend
Write-Host "🎨 Starting Frontend Server (Port 3000)..." -ForegroundColor Blue
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"

Write-Host ""
Write-Host "✅ Alphabot is starting up!" -ForegroundColor Green
Write-Host ""
Write-Host "📍 Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "📍 Backend:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "📍 API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C in each terminal window to stop the servers" -ForegroundColor Yellow
