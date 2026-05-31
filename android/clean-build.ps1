# Gradle 데몬이 build\...\merged_res_blame_folder\out 핸들을 안 놓아
# Clean/빌드 시 "Unable to delete directory ... process has files open"가 날 때 실행.
# Gradle/Kotlin 데몬(java.exe) 종료 + app\build 삭제 → Studio에서 다시 Run.
#   사용:  powershell -ExecutionPolicy Bypass -File android\clean-build.ps1
Get-Process java -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 700
Remove-Item "$PSScriptRoot\app\build" -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path "$PSScriptRoot\app\build") {
    Write-Host "일부 파일이 아직 잠겨 있습니다. Android Studio를 닫고 다시 실행하세요." -ForegroundColor Yellow
} else {
    Write-Host "완료: 데몬 종료 + build 삭제. 이제 Studio에서 Run 하세요." -ForegroundColor Green
}
