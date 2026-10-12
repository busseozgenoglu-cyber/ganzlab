# SesKlon — Windows (PowerShell) çalıştırma betiği. Gereksinimler: Python 3.11, Node 20, ffmpeg (PATH'te), git.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) { py -3.11 -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install -q --upgrade pip
pip install -q -r backend\requirements.txt
if (-not (Test-Path "frontend\dist")) { Push-Location frontend; npm install --silent; npm run build; Pop-Location }
$env:FRONTEND_DIST = "$PSScriptRoot\frontend\dist"
Set-Location backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
