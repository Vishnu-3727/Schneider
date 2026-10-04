#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Checking that Docker is running..."
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop, wait until it says Running, then run this again."
  exit 1
fi
echo "Starting the database, MQTT broker and backend..."
docker compose up -d --build db mqtt backend
echo "Waiting for the backend at http://localhost:8000/health/components ..."
waited=0
until curl -fs http://localhost:8000/health/components >/dev/null 2>&1; do
  sleep 3
  waited=$((waited + 3))
  if [ "$waited" -ge 180 ]; then
    echo "Backend did not start. See: docker compose logs backend"
    exit 1
  fi
done
echo "Creating the database..."
docker compose exec -T backend python scripts/setup/init_db.py
echo "Loading the simulated plant demo data..."
if ! docker compose exec -T backend python scripts/demo/run_demo.py; then
  echo "run_demo.py failed. See: docker compose logs backend"
  exit 1
fi
echo "Opening the console in your browser..."
url="http://localhost:8000/console/"
if command -v open >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
  open "$url"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url"
else
  echo "$url"
fi
echo "JouleMitra is running at http://localhost:8000/console/"
echo "Stop it with: docker compose down"
