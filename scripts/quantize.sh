#!/usr/bin/env bash
# GGUF 변환 + 양자화 (여러 레벨 일괄)
#
# 사용:
#   bash scripts/quantize.sh models/merged/r3-qwen models/gguf/r3-qwen
#
# 전제: ../llama.cpp 가 빌드되어 있어야 함
#   git clone https://github.com/ggerganov/llama.cpp
#   cd llama.cpp && cmake -B build && cmake --build build --config Release
#   pip install -r llama.cpp/requirements.txt
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "사용법: $0 <merged_model_dir> <out_dir> [llama_cpp_dir]"
  exit 1
fi

MERGED="$1"
OUT="$2"
LLAMA_CPP="${3:-../llama.cpp}"
NAME="$(basename "$MERGED")"

mkdir -p "$OUT"

# 1. HF → GGUF (FP16)  — PYTHON 환경변수로 venv python 지정 가능 (기본 python)
echo "[quantize] HF → GGUF FP16"
"${PYTHON:-python}" "$LLAMA_CPP/convert_hf_to_gguf.py" "$MERGED" \
  --outfile "$OUT/${NAME}.f16.gguf" \
  --outtype f16

# llama-quantize 바이너리 탐색 (CMake build/bin, Windows build_bin/.exe, 루트 폴백 모두 대응)
QUANT_BIN=""
for cand in \
  "$LLAMA_CPP/build/bin/llama-quantize" "$LLAMA_CPP/build/bin/llama-quantize.exe" \
  "$LLAMA_CPP/build_bin/llama-quantize" "$LLAMA_CPP/build_bin/llama-quantize.exe" \
  "$LLAMA_CPP/llama-quantize" "$LLAMA_CPP/llama-quantize.exe"; do
  if [ -f "$cand" ]; then QUANT_BIN="$cand"; break; fi
done
if [ -z "$QUANT_BIN" ]; then
  echo "[quantize] llama-quantize 바이너리를 못 찾음 — $LLAMA_CPP 빌드 확인"; exit 1
fi
echo "[quantize] binary: $QUANT_BIN"

# 2. 여러 양자화 레벨
for Q in Q8_0 Q5_K_M Q4_K_M Q3_K_M IQ3_M; do
  echo "[quantize] $Q"
  "$QUANT_BIN" \
    "$OUT/${NAME}.f16.gguf" \
    "$OUT/${NAME}.${Q}.gguf" \
    "$Q"
done

echo "[quantize] 완료. 파일 크기:"
ls -lh "$OUT"
