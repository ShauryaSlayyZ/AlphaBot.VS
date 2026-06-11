@echo off
echo ========================================================
echo Starting Alphabot v2.0...
echo ========================================================
echo.

:: Check if databases exist by checking for one of them
if not exist "backend\diablo_canyon.db" (
    echo [INFO] Setting up databases...
    cd backend
    python setup_databases.py
    cd ..
    echo [INFO] Databases created!
    echo.
)

echo [INFO] Starting Backend Server (Port 8000)...
start "Backend Server" cmd /c "cd backend && python -m uvicorn main:app --reload --port 8000"

:: Wait a few seconds for backend to initialize
timeout /t 3 /nobreak > nul

echo [INFO] Starting Frontend Server (Port 3000)...
start "Frontend Server" cmd /c "cd frontend && npm run dev"

echo.
echo ========================================================
echo Alphabot is starting up!
echo ========================================================
echo.
echo Frontend: http://localhost:3000
echo Backend:  http://127.0.0.1:8000
echo API Docs: http://127.0.0.1:8000/docs
echo.
echo Press any key to exit this script... (The servers will remain running in new windows)
pause > nul
