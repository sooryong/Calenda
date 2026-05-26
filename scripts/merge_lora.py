"""LoRA 어댑터를 베이스 모델에 merge하여 단일 FP16 모델로 저장.

사용:
    python scripts/merge_lora.py --base Qwen/Qwen2.5-0.5B-Instruct --lora models/lora/v1 --out models/merged/v1
"""
from __future__ import annotations

import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="베이스 모델 HF ID 또는 로컬 경로")
    ap.add_argument("--lora", required=True, help="LoRA 어댑터 디렉토리")
    ap.add_argument("--out", required=True, help="merged 모델 출력 디렉토리")
    ap.add_argument("--trust_remote_code", action="store_true")
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"[merge] base={args.base}")
    print(f"[merge] lora={args.lora}")

    tokenizer = AutoTokenizer.from_pretrained(args.base, trust_remote_code=args.trust_remote_code)
    base = AutoModelForCausalLM.from_pretrained(
        args.base,
        torch_dtype=torch.float16,
        device_map="cpu",  # merge는 CPU에서도 충분히 빠름 (0.5B)
        trust_remote_code=args.trust_remote_code,
    )
    model = PeftModel.from_pretrained(base, args.lora)
    merged = model.merge_and_unload()

    merged.save_pretrained(args.out, safe_serialization=True)
    tokenizer.save_pretrained(args.out)
    print(f"[merge] 완료 → {args.out}")


if __name__ == "__main__":
    main()
