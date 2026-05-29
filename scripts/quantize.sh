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

# 1. HF → GGUF (FP16)
echo "[quantize] HF → GGUF FP16"
python "$LLAMA_CPP/convert_hf_to_gguf.py" "$MERGED" \
  --outfile "$OUT/${NAME}.f16.gguf" \
  --outtype f16

QUANT_BIN="$LLAMA_CPP/build/bin/llama-quantize"
if [ ! -x "$QUANT_BIN" ]; then
  QUANT_BIN="$LLAMA_CPP/llama-quantize"  # 구버전 폴백
fi

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
