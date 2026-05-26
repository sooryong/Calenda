"""Generator — Planner의 시나리오에서 (메시지, gold) 페어를 생성.

사용:
    python scripts/generate.py --plan data/raw/plan_v1.json --out data/raw/v1.jsonl
    python scripts/generate.py --plan ... --out ... --restart   # 기존 출력 무시
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from _common import call_claude, load_prompt, read_jsonl

# 파이프/리다이렉트 환경에서도 진행 출력이 즉시 보이도록 line-buffer 강제
try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
except Exception:
    pass

SYSTEM_RE = re.compile(r"## System Prompt\s*```(.*?)```", re.DOTALL)
USER_RE = re.compile(r"## User Prompt 템플릿\s*```(.*?)```", re.DOTALL)
FEW_SHOT_RE = re.compile(r"### 예시 \d+:.*?\n```\n(.*?)\n```", re.DOTALL)

BATCH_SIZE = 10  # 한 번 API 호출로 생성할 최대 건수


def extract_sections() -> tuple[str, str]:
    md = load_prompt("generator")
    system = SYSTEM_RE.search(md).group(1).strip()
    user = USER_RE.search(md).group(1).strip()
    return system, user


def load_few_shots() -> list[str]:
    md = load_prompt("generator")
    return FEW_SHOT_RE.findall(md)


def parse_jsonl_text(text: str) -> list[dict]:
    """모델이 뱉은 JSONL 형식 텍스트를 dict 리스트로."""
    rows = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


class Progress:
    """누적 생성 건수를 thread-safe하게 추적."""

    def __init__(self, total_target: int, already_done: int):
        self.total_target = total_target
        self.cumulative = already_done
        self.lock = threading.Lock()
        self.start_time = time.time()

    def add(self, n: int) -> tuple[int, float, float]:
        with self.lock:
            self.cumulative += n
            pct = (self.cumulative / self.total_target * 100) if self.total_target else 0.0
            elapsed = time.time() - self.start_time
            return self.cumulative, pct, elapsed


def append_jsonl(path: Path, rows: list[dict], lock: threading.Lock) -> None:
    if not rows:
        return
    with lock:
        with open(path, "ab") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False).encode("utf-8"))
                f.write(b"\n")


def existing_counts(path: Path) -> dict[str, int]:
    """출력 파일에서 scenario_id별 행 수 산출 (resume용)."""
    if not path.exists():
        return {}
    counts: collections.Counter = collections.Counter()
    for row in read_jsonl(path):
        sid = row.get("scenario_id")
        if sid:
            counts[sid] += 1
    return dict(counts)


def generate_for_scenario(
    system: str,
    user_tmpl: str,
    scenario: dict,
    remaining: int,
    few_shots: list[str],
    model: str,
    out_path: Path,
    file_lock: threading.Lock,
    progress: Progress,
) -> int:
    sid = scenario.get("scenario_id", "?")
    fs = "\n\n".join(few_shots[:3])
    n_batches = math.ceil(remaining / BATCH_SIZE)
    batch_num = 0
    produced = 0
    while remaining > 0:
        batch = min(remaining, BATCH_SIZE)
        batch_num += 1
        sc = dict(scenario)
        sc["count"] = batch
        user = (
            user_tmpl.replace("{count}", str(batch))
            .replace("{scenario_json}", json.dumps(sc, ensure_ascii=False, indent=2))
            .replace("{few_shot_examples}", fs)
        )
        t0 = time.time()
        try:
            out = call_claude(
                system=system, user=user, model=model, max_tokens=8000, temperature=0.9
            )
            parsed = parse_jsonl_text(out)
        except Exception as e:
            print(f"  [ERR] {sid} 배치 {batch_num}/{n_batches}: {e}", flush=True)
            remaining -= batch
            continue
        for r in parsed:
            r.setdefault("scenario_id", sid)
        append_jsonl(out_path, parsed, file_lock)
        produced += len(parsed)
        remaining -= batch
        elapsed = time.time() - t0
        cum, pct, total_elapsed = progress.add(len(parsed))
        rate = cum / total_elapsed if total_elapsed > 0 else 0
        eta_sec = (progress.total_target - cum) / rate if rate > 0 else 0
        print(
            f"[{cum:>5}/{progress.total_target} {pct:5.1f}%] {sid} "
            f"배치 {batch_num}/{n_batches} +{len(parsed)}건 ({elapsed:.0f}s) "
            f"ETA {eta_sec/60:.1f}분",
            flush=True,
        )
    return produced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--restart",
        action="store_true",
        help="기존 출력 파일을 삭제하고 처음부터 다시 생성",
    )
    args = ap.parse_args()

    system, user_tmpl = extract_sections()
    few_shots = load_few_shots()

    scenarios = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    target_total = sum(s.get("count", 0) for s in scenarios)

    out_path = Path(args.out)
    if args.restart and out_path.exists():
        out_path.unlink()
        print(f"[generate] --restart: {out_path} 삭제", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done_counts = existing_counts(out_path)
    done_total = sum(done_counts.values())

    todo: list[tuple[dict, int]] = []
    for sc in scenarios:
        sid = sc.get("scenario_id")
        need = sc.get("count", 0) - done_counts.get(sid, 0)
        if need > 0:
            todo.append((sc, need))

    print(
        f"[generate] plan={len(scenarios)} target={target_total} "
        f"기존={done_total} todo시나리오={len(todo)} 부족={target_total - done_total} "
        f"model={args.model} workers={args.workers}",
        flush=True,
    )
    if not todo:
        print("[generate] 이미 목표 달성. 추가 생성 없음.", flush=True)
        return

    progress = Progress(total_target=target_total, already_done=done_total)
    file_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(
                generate_for_scenario,
                system,
                user_tmpl,
                sc,
                need,
                few_shots,
                args.model,
                out_path,
                file_lock,
                progress,
            ): sc
            for sc, need in todo
        }
        for fut in as_completed(futures):
            sc = futures[fut]
            sid = sc.get("scenario_id")
            try:
                produced = fut.result()
                print(f"✓ {sid} 완료 (이번 라운드 +{produced}건)", flush=True)
            except Exception as e:
                print(f"✗ {sid} 실패: {e}", flush=True)

    final_counts = existing_counts(out_path)
    final_total = sum(final_counts.values())
    pct = (final_total / target_total * 100) if target_total else 0.0
    print(
        f"[generate] DONE — 총 {final_total}/{target_total}건 ({pct:.1f}%) → {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
