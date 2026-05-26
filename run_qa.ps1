Set-Location D:\calendar-agent
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
& .\.venv\Scripts\python.exe -u scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl --workers 4 2>&1 | Tee-Object -FilePath D:\calendar-agent\logs\qa_v1.log
Write-Host "DONE exit=$LASTEXITCODE"
