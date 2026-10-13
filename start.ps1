# Starts the API (with embedded worker) and serves the built UI on http://127.0.0.1:8000
# First run:  backend: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
#             frontend: npm install; npm run build
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "backend")
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
