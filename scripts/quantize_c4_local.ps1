# quantize_c4_local.ps1 — c4 LoRA 어댑터 zip → merged → Q8_0 GGUF (로컬 Windows)
#
# 사용: PowerShell에서  .\scripts\quantize_c4_local.ps1
#   기본값은 c4. 다른 라운드면 $NAME 만 바꾸면 됨.
#
# 전제:
#   - .venv 활성화 가능 (merge용 torch/peft/transformers = pip install -e .[train])
#   - llama.cpp 가 D:\Calenda\..\llama.cpp 에 빌드돼 있어야 함 (없으면 아래 안내대로 1회 빌드)
#       git clone https://github.com/ggml-org/llama.cpp ..\llama.cpp
#       cmake -S ..\llama.cpp -B ..\llama.cpp\build -DGGML_CUDA=OFF -DLLAMA_CURL=OFF
#       cmake --build ..\llama.cpp\build --config Release --target llama-quantize
#       pip install gguf
#
# 빌드 환경이 부담되면: Colab에서 notebooks\calendar_quantize.ipynb (SOURCE="upload")로
#   lora_c4-qwen3-0.6b.zip 업로드 → merge+Q8_0 한 번에 (로컬 빌드 불필요).

$ErrorActionPreference = "Stop"
$NAME   = "c4-qwen3-0.6b"
$BASE   = "Qwen/Qwen3-0.6B"
$ROOT   = "D:\Calenda"
$ZIP    = "$ROOT\models\lora\lora_$NAME.zip"
$LORA   = "$ROOT\models\lora\$NAME"
$MERGED = "$ROOT\models\merged\$NAME"
$GGUF   = "$ROOT\models\gguf\$NAME"
$LLAMA  = "$ROOT\..\llama.cpp"

Set-Location $ROOT

# 0) venv
if (Test-Path "$ROOT\.venv\Scripts\Activate.ps1") { & "$ROOT\.venv\Scripts\Activate.ps1" }

# 1) 어댑터 압축 해제 (zip 루트에 adapter_*.* 가 바로 들어 있음)
Write-Host "[1/4] 어댑터 압축 해제 -> $LORA"
if (Test-Path $LORA) { Remove-Item -Recurse -Force $LORA }
Expand-Archive -Path $ZIP -DestinationPath $LORA -Force
if (-not (Test-Path "$LORA\adapter_config.json")) {
    # 일부 zip은 한 단계 더 들어가 있음 — 평탄화
    $sub = Get-ChildItem $LORA -Directory | Select-Object -First 1
    if ($sub -and (Test-Path "$($sub.FullName)\adapter_config.json")) {
        Get-ChildItem $sub.FullName | Move-Item -Destination $LORA -Force
    }
}
if (-not (Test-Path "$LORA\adapter_config.json")) { throw "adapter_config.json 못 찾음 — zip 구조 확인" }

# 2) merge (LoRA -> FP16)
Write-Host "[2/4] merge -> $MERGED"
python scripts\merge_lora.py --base $BASE --lora $LORA --out $MERGED

# 3) llama.cpp 확인
$QUANT = $null
foreach ($c in @("$LLAMA\build\bin\Release\llama-quantize.exe","$LLAMA\build\bin\llama-quantize.exe","$LLAMA\build\bin\llama-quantize")) {
    if (Test-Path $c) { $QUANT = $c; break }
}
if (-not $QUANT) {
    Write-Host "`n[!] llama.cpp 미빌드. 1회 설치:" -ForegroundColor Yellow
    Write-Host "    git clone https://github.com/ggml-org/llama.cpp `"$LLAMA`""
    Write-Host "    cmake -S `"$LLAMA`" -B `"$LLAMA\build`" -DGGML_CUDA=OFF -DLLAMA_CURL=OFF"
    Write-Host "    cmake --build `"$LLAMA\build`" --config Release --target llama-quantize"
    Write-Host "    pip install gguf"
    Write-Host "  빌드 후 이 스크립트를 다시 실행하세요. (merged 는 이미 만들어졌으니 2단계는 스킵됨)"
    Write-Host "  또는 Colab calendar_quantize.ipynb 사용 (빌드 불필요)."
    exit 1
}

# 4) f16 변환 + Q8_0 양자화
New-Item -ItemType Directory -Force -Path $GGUF | Out-Null
$F16 = "$GGUF\$NAME.f16.gguf"
$OUT = "$GGUF\$NAME.Q8_0.gguf"
Write-Host "[3/4] HF -> GGUF f16"
python "$LLAMA\convert_hf_to_gguf.py" $MERGED --outfile $F16 --outtype f16
Write-Host "[4/4] 양자화 Q8_0"
& $QUANT $F16 $OUT Q8_0

$mb = [math]::Round((Get-Item $OUT).Length / 1MB)
Write-Host "`n완료 -> $OUT  (${mb}MB)" -ForegroundColor Green
Write-Host "이 파일이 폰 배포본(Q8_0)입니다. android\app\src\main\assets\ 로 임포트."
