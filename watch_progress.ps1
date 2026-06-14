Set-Location D:\calenda
$outPath = "data\raw\v1.jsonl"
$milestonePath = "logs\milestones.log"
$target = 3620
$startedAt = [datetime]::Now

# 시작 시 이미 기존 행이 있을 수 있음 → 그 시점 % 위 첫 10% 단위가 다음 임계
$initial = (Get-Content $outPath | Measure-Object -Line).Lines
$nextPct = [int]([math]::Floor($initial / $target * 10) + 1) * 10
"$([datetime]::Now.ToString('HH:mm:ss')) [start] cum=$initial/$target ($([math]::Round($initial/$target*100,1))%) next_milestone=$nextPct%" | Tee-Object -FilePath $milestonePath

while ($true) {
    Start-Sleep -Seconds 5
    if (-not (Test-Path $outPath)) { continue }
    $cum = (Get-Content $outPath | Measure-Object -Line).Lines
    $pct = $cum / $target * 100
    while ($pct -ge $nextPct -and $nextPct -le 100) {
        $elapsed = ([datetime]::Now - $startedAt).TotalMinutes
        $line = "$([datetime]::Now.ToString('HH:mm:ss')) [{0,3}%] cum={1}/{2}  elapsed={3:N1}분" -f $nextPct, $cum, $target, $elapsed
        Add-Content -Path $milestonePath -Value $line
        Write-Host $line
        $nextPct += 10
    }
    if ($cum -ge $target) { break }
}
"$([datetime]::Now.ToString('HH:mm:ss')) [done] cum=$cum/$target" | Tee-Object -FilePath $milestonePath -Append
