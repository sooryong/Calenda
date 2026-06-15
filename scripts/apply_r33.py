"""r33 데이터 적용 — 환각 억제 하드케이스(_r33_add.jsonl)를 train.jsonl에 dedup append.

전제: 필드 정합은 이미 `relabel_fields_haiku.py --apply`로 train.jsonl에 반영됨(location 채움·attendees 정리).
이 스크립트는 그 위에 _r33_add(무시간/무장소/무설명 양성)를 누적한다.
append 워크플로 — assemble_train --apply 금지(SOURCES r24 stale → 회귀). [[train-jsonl-append-workflow]]

사용:
    python scripts/apply_r33.py            # dry-run(통계만)
    python scripts/apply_r33.py --apply    # train.jsonl 실제 갱신
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

TRAIN = Path("data/processed/train.jsonl")
ADD = Path("data/processed/_r33_add.jsonl")


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def key(r: dict) -> str:
    return f"{r.get('channel','')}|{r.get('message','')}|{json.dumps(r.get('gold',{}), ensure_ascii=False, sort_keys=True)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    train = load(TRAIN)
    add = load(ADD)
    n0 = len(train)

    seen = {key(r) for r in train}
    new, dup = [], 0
    for r in add:
        k = key(r)
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        new.append(r)
    merged = train + new

    # 검증: 양성 round-trip resolve
    bad = 0
    for r in merged:
        if not r.get("gold", {}).get("has_schedule"):
            continue
        for ev in r["gold"].get("events", []):
            res = resolve_when(r["received_at"], ev.get("date"), ev.get("time"),
                               ev.get("end_time"), ev.get("all_day", False))
            if ev.get("date") and res["start"] is None:
                bad += 1
                print("  ! resolve 실패:", r.get("scenario_id"), repr(ev.get("date")))

    pos = sum(1 for r in merged if r.get("gold", {}).get("has_schedule"))
    neg = len(merged) - pos
    print(f"기존 {n0}행 + add {len(add)}(신규 {len(new)}, dup {dup}) → {len(merged)}행")
    print(f"양성 {pos} · 음성 {neg} = {neg/len(merged)*100:.1f}% neg | resolve 실패 {bad}")
    if not args.apply:
        print("dry-run (적용하려면 --apply)")
        return
    if bad:
        print("⚠ resolve 실패가 있어 미적용. 데이터 확인 요망.")
        return
    TRAIN.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in merged) + "\n", encoding="utf-8")
    print(f"✓ {TRAIN} 갱신")


if __name__ == "__main__":
    main()
