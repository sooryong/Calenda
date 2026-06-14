"""r31 데이터 적용 — train.jsonl에 (1) confidence 재bump + (2) _r31_add 병합.

최근 라운드(r27~r30)는 assemble SOURCES를 안 거치고 _rNN_add.jsonl을 train.jsonl에 직접 누적해왔다.
r31도 동일하게 append하여 r28/r30 데이터 회귀를 피한다. (assemble_train --apply 금지: SOURCES가 r24까지라 회귀.)

(1) confidence 재bump — 새 루브릭('장소 의존 제거'): 날짜+시간+활동(제목)이 분명하면 0.90+.
    기존 gold의 'date·time.hour·title 모두 있음 & conf<0.9'(장소 없다고 깎인 것 추정)을 0.90으로 상향.
(2) _r31_add.jsonl(온라인 도구 장소 양성 + 도구명 하드네거티브)을 dedup 후 append.

사용:
    python scripts/apply_r31.py            # dry-run(통계만)
    python scripts/apply_r31.py --apply    # train.jsonl 실제 갱신
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

TRAIN = Path("data/processed/train.jsonl")
ADD = Path("data/processed/_r31_add.jsonl")
REBUMP_TO = 0.90


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def key(r: dict) -> str:
    return f"{r.get('channel','')}|{r.get('message','')}|{json.dumps(r.get('gold',{}), ensure_ascii=False, sort_keys=True)}"


def is_clear(ev: dict) -> bool:
    """날짜+시간(hour)+활동(제목) 모두 분명 → 새 루브릭상 0.90+ 확정."""
    t = ev.get("time") or {}
    return bool(ev.get("date")) and t.get("hour") is not None and bool((ev.get("title") or "").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    train = load(TRAIN)
    add = load(ADD)
    n0 = len(train)

    # (1) 재bump
    bumped = 0
    for r in train:
        if not r.get("gold", {}).get("has_schedule"):
            continue
        for ev in r["gold"].get("events", []):
            c = ev.get("confidence")
            if is_clear(ev) and isinstance(c, (int, float)) and c < REBUMP_TO:
                ev["confidence"] = REBUMP_TO
                bumped += 1

    # (2) append (dedup)
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
            res = resolve_when(r["received_at"], ev.get("date"), ev.get("time"), ev.get("end_time"), ev.get("all_day", False))
            if ev.get("date") and res["start"] is None:
                bad += 1
                print("  ! resolve 실패:", r.get("scenario_id"), repr(ev.get("date")))

    pos = sum(1 for r in merged if r.get("gold", {}).get("has_schedule"))
    neg = len(merged) - pos
    print(f"기존 {n0}행 → 재bump {bumped}건 / add {len(add)}(신규 {len(new)}, dup {dup})")
    print(f"결과 {len(merged)}행 (양성 {pos} · 음성 {neg} = {neg/len(merged)*100:.1f}% neg) | resolve 실패 {bad}")
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
