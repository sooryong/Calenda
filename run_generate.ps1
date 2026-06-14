Set-Location D:\calenda
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# -u : unbuffered stdout/stderr → Tee-Object로 즉시 흘러나오게
& .\.venv\Scripts\python.exe -u scripts/generate.py --plan data/raw/plan_v1.json --out data/raw/v1.jsonl --workers 2 2>&1 | Tee-Object -FilePath D:\calenda\logs\generate_v1.log
Write-Host "DONE exit=$LASTEXITCODE"
