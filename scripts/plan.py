"""Planner — 시나리오 명세서를 생성한다.

사용:
    python scripts/plan.py --out data/raw/plan_v1.json [--failures data/failures/round_0.jsonl]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _common import (
    call_claude,
    extract_json_block,
    load_prompt,
    read_jsonl,
    safe_json_loads,
)

PLANNER_SYSTEM_RE = re.compile(r"## System Prompt\s*```(.*?)```", re.DOTALL)
PLANNER_INITIAL_RE = re.compile(r"## User Prompt \(초기 라운드\)\s*```(.*?)```", re.DOTALL)
PLANNER_LOOP_RE = re.compile(r"## User Prompt \(폐루프 라운드.*?\)\s*```(.*?)```", re.DOTALL)


def extract_sections() -> tuple[str, str, str]:
    """prompts/planner.md에서 system / initial-user / loop-user 추출."""
    md = load_prompt("planner")
    system = PLANNER_SYSTEM_RE.search(md).group(1).strip()
    initial = PLANNER_INITIAL_RE.search(md).group(1).strip()
    loop = PLANNER_LOOP_RE.search(md).group(1).strip()
    return system, initial, loop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="시나리오 명세서 출력 경로 (json)")
    ap.add_argument(
        "--failures",
        default=None,
        help="직전 라운드 실패 케이스 jsonl. 주면 폐루프 모드로 동작.",
    )
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()

    system, initial_user, loop_user = extract_sections()

    if args.failures:
        failure_rows = list(read_jsonl(args.failures))
        # 너무 많으면 상위 N개만
        failure_rows = failure_rows[:200]
        round_n = 2  # TODO: 자동 산출 (output_dir 스캔)
        user = loop_user.replace("{N}", str(round_n)).replace(
            "{failure_patterns_json}", json.dumps(failure_rows, ensure_ascii=False, indent=2)
        )
    else:
        user = initial_user

    print(f"[plan] model={args.model}, failures={'on' if args.failures else 'off'}")
    out_text = call_claude(system=system, user=user, model=args.model, max_tokens=16000, temperature=0.4)

    parsed = safe_json_loads(out_text)
    if parsed is None:
        raise RuntimeError(f"Planner 출력 JSON 파싱 실패. 원본 앞부분:\n{out_text[:500]}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(s.get("count", 0) for s in parsed)
    print(f"[plan] 시나리오 {len(parsed)}개, 합산 count={total} → {args.out}")


if __name__ == "__main__":
    main()
