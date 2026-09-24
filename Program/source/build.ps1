$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "构建失败，退出码 $LASTEXITCODE" } }
if (!(Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv; Check-Exit }
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
Check-Exit
Push-Location frontend
try {
    npm.cmd ci
    Check-Exit
    npm.cmd run build
    Check-Exit
} finally { Pop-Location }
$frontendDist = (Resolve-Path 'frontend/dist').Path
& '.venv/Scripts/python.exe' -m PyInstaller --noconfirm --clean --onefile --windowed --name FlowDesk --distpath release --workpath build --paths . --add-data "$frontendDist;frontend/dist" --collect-submodules uvicorn --hidden-import sqlalchemy.dialects.sqlite --hidden-import sqlalchemy.dialects.postgresql.psycopg launcher.py
Check-Exit
Write-Host '完成：release/FlowDesk.exe'
