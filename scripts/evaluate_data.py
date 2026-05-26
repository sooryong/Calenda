"""Evaluator (데이터 QA) — Generator가 만든 페어의 품질을 검증/수정/거절.

사용:
    python scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl
    python scripts/evaluate_data.py --in ... --out ... --restart  # 기존 결과 무시
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _common import call_claude, load_prompt, read_jsonl, safe_json_loads

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
except Exception:
    pass

SYSTEM_RE = re.compile(r"## 1\. 데이터 품질 검증자.*?### System Prompt\s*```(.*?)```", re.DOTALL)
USER_RE = re.compile(r"## 1\. 데이터 품질 검증자.*?### User Prompt\s*```(.*?)```", re.DOTALL)


def extract_sections() -> tuple[str, str]:
    md = load_prompt("evaluator")
    system = SYSTEM_RE.search(md).group(1).strip()
    user = USER_RE.search(md).group(1).strip()
    return system, user


def pair_key(pair: dict) -> str:
    """페어의 고유 식별자 — message + received_at의 hash. Resume 매칭에 사용."""
    s = (pair.get("message", "") + "|" + pair.get("received_at", "")).encode("utf-8")
    return hashlib.md5(s).hexdigest()


def verify_pair(
    system: str, user_tmpl: str, pair: dict, model: str
) -> tuple[str, dict | None, dict]:
    user = user_tmpl.replace("{pair_json}", json.dumps(pair, ensure_ascii=False, indent=2))
    out = call_claude(system=system, user=user, model=model, max_tokens=2000, temperature=0.0)
    verdict_obj = safe_json_loads(out) or {
        "verdict": "reject",
        "issues": [{"raw": out[:200]}],
        "fixed_gold": None,
    }
    verdict = verdict_obj.get("verdict", "reject")
    if verdict == "fix" and verdict_obj.get("fixed_gold"):
        fixed = dict(pair)
        fixed["gold"] = verdict_obj["fixed_gold"]
        fixed["_qa"] = verdict_obj
        return "fix", fixed, verdict_obj
    if verdict == "accept":
        out_pair = dict(pair)
        out_pair["_qa"] = verdict_obj
        return "accept", out_pair, verdict_obj
    return "reject", None, verdict_obj


def append_jsonl(path: Path, row: dict, lock: threading.Lock) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as f:
            f.write(json.dumps(row, ensure_ascii=False).encode("utf-8"))
            f.write(b"\n")


def load_processed_keys(out_path: Path, rej_path: Path) -> set[str]:
    seen: set[str] = set()
    for p in [out_path, rej_path]:
        if p.exists():
            for row in read_jsonl(p):
                seen.add(pair_key(row))
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rejected", default=None, help="reject 페어 저장 경로")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--restart", action="store_true", help="기존 출력 삭제 후 처음부터")
    ap.add_argument("--log-every", type=int, default=20, help="N건마다 진행 출력")
    args = ap.parse_args()

    system, user_tmpl = extract_sections()
    pairs = list(read_jsonl(args.inp))
    total_input = len(pairs)

    out_path = Path(args.out)
    rej_path = Path(args.rejected or "data/failures/qa_rejected.jsonl")

    if args.restart:
        for p in [out_path, rej_path]:
            if p.exists():
                p.unlink()
                print(f"[evaluate_data] --restart: {p} 삭제", flush=True)

    processed_keys = load_processed_keys(out_path, rej_path)
    todo = [p for p in pairs if pair_key(p) not in processed_keys]

    # 기존 통계 (resume 시 누적 표시용)
    stats = {"accept": 0, "fix": 0, "reject": 0}
    if out_path.exists():
        for row in read_jsonl(out_path):
            v = (row.get("_qa") or {}).get("verdict", "accept")
            stats[v if v in stats else "accept"] += 1
    if rej_path.exists():
        stats["reject"] += sum(1 for _ in read_jsonl(rej_path))

    print(
        f"[evaluate_data] input={total_input} 기존처리={len(processed_keys)} todo={len(todo)} "
        f"model={args.model} workers={args.workers}",
        flush=True,
    )
    if not todo:
        print("[evaluate_data] 모든 페어 처리 완료.", flush=True)
        return

    file_lock = threading.Lock()
    counter_lock = threading.Lock()
    counters = {"done": 0}
    start = time.time()
    base_done = len(processed_keys)

    def process_one(pair: dict):
        try:
            verdict, fixed_pair, raw = verify_pair(system, user_tmpl, pair, args.model)
        except Exception as e:
            verdict, fixed_pair, raw = "reject", None, {"error": str(e)}
        if fixed_pair is not None:
            append_jsonl(out_path, fixed_pair, file_lock)
        else:
            rej = dict(pair)
            rej["_qa"] = raw
            append_jsonl(rej_path, rej, file_lock)

        with counter_lock:
            counters["done"] += 1
            stats[verdict] = stats.get(verdict, 0) + 1
            done = counters["done"]
            cum_total = base_done + done
            should_log = done % args.log_every == 0 or done == len(todo)
            if should_log:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta_sec = (len(todo) - done) / rate if rate > 0 else 0
                pct = cum_total / total_input * 100 if total_input else 0
                line = (
                    f"[{cum_total:>5}/{total_input} {pct:5.1f}%] "
                    f"accept={stats['accept']} fix={stats['fix']} reject={stats['reject']} "
                    f"(rate={rate:.1f}/s ETA {eta_sec/60:.1f}분)"
                )
            else:
                line = None
        if line:
            print(line, flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(process_one, todo))

    total = stats["accept"] + stats["fix"] + stats["reject"]
    rej_pct = 100 * stats["reject"] / max(1, total)
    print(
        f"[evaluate_data] DONE — accept={stats['accept']} fix={stats['fix']} "
        f"reject={stats['reject']} / total={total} ({rej_pct:.1f}% rejected)",
        flush=True,
    )
    print(f"  채택: {out_path}", flush=True)
    print(f"  거절: {rej_path}", flush=True)


if __name__ == "__main__":
    main()
