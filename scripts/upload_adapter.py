"""LoRA 어댑터를 HuggingFace Hub에 업로드한다.

사용:
    python scripts/upload_adapter.py \
        --adapter models/lora/c27-qwen3-0.6b \
        --repo sooryong9885/Calenda-Qwen3-0.6B \
        --subfolder c27-qwen3-0.6b

HF_TOKEN 환경변수 또는 ~/.cache/huggingface/token 으로 인증.
eval.json / failures.jsonl 이 있으면 함께 업로드한다.
"""
import argparse, os, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter",    required=True,  help="LoRA 어댑터 디렉토리")
    ap.add_argument("--repo",       required=True,  help="HF repo id (owner/name)")
    ap.add_argument("--subfolder",  required=True,  help="repo 내 서브폴더명 (예: c27-qwen3-0.6b)")
    ap.add_argument("--eval",       default=None,   help="eval JSON 경로 (선택)")
    ap.add_argument("--failures",   default=None,   help="failures JSONL 경로 (선택)")
    args = ap.parse_args()

    from huggingface_hub import HfApi
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    api = HfApi(token=token)

    adapter_dir = Path(args.adapter)
    if not adapter_dir.exists():
        sys.exit(f"[upload] 어댑터 디렉토리 없음: {adapter_dir}")

    # 어댑터 파일 업로드 (checkpoint 폴더 제외)
    skip = {"optimizer.pt", "rng_state_0.pth", "rng_state_1.pth", "scheduler.pt", "training_args.bin"}
    uploaded = []
    for f in sorted(adapter_dir.rglob("*")):
        if f.is_dir():
            continue
        if any(part.startswith("checkpoint-") for part in f.parts):
            continue
        if f.name in skip:
            continue
        rel = f.relative_to(adapter_dir)
        path_in_repo = f"{args.subfolder}/{rel}"
        api.upload_file(path_or_fileobj=str(f), path_in_repo=path_in_repo, repo_id=args.repo, repo_type="model")
        uploaded.append(path_in_repo)
        print(f"  ↑ {path_in_repo}")

    # eval.json 업로드
    eval_path = args.eval or f"logs/eval_{adapter_dir.name}.json"
    if Path(eval_path).exists():
        api.upload_file(path_or_fileobj=eval_path,
                        path_in_repo=f"{args.subfolder}/eval.json",
                        repo_id=args.repo, repo_type="model")
        print(f"  ↑ {args.subfolder}/eval.json")

    # failures.jsonl 업로드
    fail_path = args.failures or "data/failures/round_latest.jsonl"
    if Path(fail_path).exists():
        api.upload_file(path_or_fileobj=fail_path,
                        path_in_repo=f"{args.subfolder}/failures.jsonl",
                        repo_id=args.repo, repo_type="model")
        print(f"  ↑ {args.subfolder}/failures.jsonl")

    print(f"\n[upload] 완료 → https://huggingface.co/{args.repo}/tree/main/{args.subfolder}")

if __name__ == "__main__":
    main()
