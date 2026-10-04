@echo off
cd /d "%~dp0"
echo Checking that Docker is running...
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker is not running. Start Docker Desktop, wait until it says Running, then run this again.
  pause
  exit /b 1
)
echo Starting the database, MQTT broker and backend...
docker compose up -d --build db mqtt backend
if errorlevel 1 (
  echo Failed to start the containers. See: docker compose logs backend
  pause
  exit /b 1
)
echo Waiting for the backend at http://localhost:8000/health/components ...
set /a waited=0
:waitloop
curl.exe -fs http://localhost:8000/health/components >nul 2>&1
if not errorlevel 1 goto ready
ping -n 4 127.0.0.1 >nul
set /a waited+=3
if %waited% GEQ 180 (
  echo Backend did not start. See: docker compose logs backend
  pause
  exit /b 1
)
goto waitloop
:ready
echo Creating the database...
docker compose exec -T backend python scripts/setup/init_db.py
if errorlevel 1 (
  echo init_db.py failed. See: docker compose logs backend
  pause
  exit /b 1
)
echo Loading the simulated plant demo data...
docker compose exec -T backend python scripts/demo/run_demo.py
if errorlevel 1 (
  echo run_demo.py failed. See: docker compose logs backend
  pause
  exit /b 1
)
echo Opening the console in your browser...
start "" http://localhost:8000/console/
echo JouleMitra is running at http://localhost:8000/console/
echo Stop it with: docker compose down
pause
