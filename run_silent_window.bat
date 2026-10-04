@echo off
setlocal

if /I "%~1"=="backend" goto backend
if /I "%~1"=="frontend" goto frontend

set "REPO_DIR=%~dp0"

if not exist "%REPO_DIR%.venv\Scripts\python.exe" (
    echo [Silent Window] Missing .venv\Scripts\python.exe
    pause
    exit /b 1
)

if not exist "%REPO_DIR%frontend\package.json" (
    echo [Silent Window] Missing frontend\package.json
    pause
    exit /b 1
)

cd /d "%REPO_DIR%"
".venv\Scripts\python.exe" -m scripts.check_installation
if errorlevel 1 (
    echo [Silent Window] Startup checks failed. See docs\setup-guide.md.
    pause
    exit /b 1
)

echo [Silent Window] Starting backend at http://127.0.0.1:8001 ...
start "Silent Window Backend" "%ComSpec%" /k call "%~f0" backend

timeout /t 2 /nobreak >nul

echo [Silent Window] Starting frontend at http://localhost:5173 ...
start "Silent Window Frontend" "%ComSpec%" /k call "%~f0" frontend

timeout /t 4 /nobreak >nul
start "" "http://localhost:5173"

echo [Silent Window] Started. Use Ctrl+C in each server window to stop.
exit /b 0

:backend
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.check_database
if errorlevel 1 exit /b 1
echo [Silent Window Backend] Loading existing RF artifacts; no training is run.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
exit /b %errorlevel%

:frontend
cd /d "%~dp0frontend"
set "VITE_API_BASE_URL="
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
exit /b %errorlevel%
