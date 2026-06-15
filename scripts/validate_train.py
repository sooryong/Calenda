"""학습셋 객관적 전수 검증 — 스키마·날짜해석·marker규약·편향·음성비.

의미 충실성(메시지↔gold)이 아니라, 사람 판단 없이 기계로 단정할 수 있는
'명백한 결함'만 잡는다. resolver(_common)를 그대로 써서 앱/평가와 같은 기준으로 본다.

사용: python scripts/validate_train.py --in data/processed/train.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when  # 앱/평가와 동일 해석

EVENT_KEYS = {"title", "date", "time", "end_time", "all_day", "location",
              "attendees", "organizer", "description", "recurrence"}
SCHEDULE_VALS = {"yes", "pending", "no"}
MARKERS = {None, "오전", "오후", "저녁", "밤", "낮", "아침", "새벽", "정오", "자정"}


def check_row(i: int, r: dict) -> list[tuple[str, str]]:
    """행 하나의 결함 목록 [(code, detail)]."""
    out = []
    def bad(code, detail=""):
        out.append((code, detail))

    for k in ("message", "gold", "received_at", "channel"):
        if k not in r:
            bad("MISSING_FIELD", k)
    gold = r.get("gold", {})
    if not isinstance(gold, dict):
        bad("GOLD_NOT_DICT"); return out
    has = gold.get("has_schedule")
    evs = gold.get("events", [])
    if has not in SCHEDULE_VALS:
        bad("HAS_SCHEDULE_BAD", repr(has))
    if not isinstance(evs, list):
        bad("EVENTS_NOT_LIST"); return out
    # 일관성: detected(yes/pending) ⟺ events 존재
    detected = has in ("yes", "pending")
    if detected != (len(evs) > 0):
        bad("HAS_EVENTS_MISMATCH", f"has={has} n_events={len(evs)}")

    recv = r.get("received_at")
    for ev in evs:
        if not isinstance(ev, dict):
            bad("EVENT_NOT_DICT"); continue
        miss = EVENT_KEYS - set(ev.keys())
        if miss:
            bad("EVENT_MISSING_KEYS", ",".join(sorted(miss)))
        # 제목
        title = ev.get("title")
        if not title or not str(title).strip():
            bad("EMPTY_TITLE")
        elif len(str(title)) > 60:
            bad("TITLE_TOO_LONG", f"{len(str(title))}자: {title}")
        # 날짜: 있으면 resolver가 반드시 해석해야 함(미해석=학습에 독)
        date = ev.get("date")
        if date is not None:
            try:
                res = resolve_when(recv, date, None, all_day=True)["start"]
            except Exception as e:
                res = None
            if res is None:
                bad("DATE_UNRESOLVABLE", repr(date))
        elif not ev.get("all_day") and not ev.get("time"):
            # 설계: date=null + time → 앱/resolver가 오늘로 fallback(정상, 모델은 날짜를 단정 안 함).
            # 진짜 결함은 date·time 둘 다 없고 종일도 아닐 때 = 배치 불가.
            bad("UNPLACEABLE_EVENT", "date·time 모두 null, all_day=false")
        # 시각/마커
        t = ev.get("time")
        if t is not None:
            if not isinstance(t, dict):
                bad("TIME_NOT_DICT", repr(t))
            else:
                h, mk = t.get("hour"), t.get("marker")
                if not isinstance(h, int) or not (0 <= h <= 23):
                    bad("TIME_HOUR_RANGE", repr(h))
                if mk not in MARKERS:
                    bad("BAD_MARKER", repr(mk))
                # 규약: 이미 13~23시인데 오전/오후 마커 → 모순/잉여
                if isinstance(h, int) and h >= 13 and mk in ("오전", "오후", "저녁", "밤", "낮", "아침", "새벽"):
                    bad("MARKER_ON_24H", f"hour={h} marker={mk}")
        # attendees 형식
        at = ev.get("attendees")
        if at is not None and not isinstance(at, list):
            bad("ATTENDEES_NOT_LIST", repr(at))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/processed/train.jsonl")
    ap.add_argument("--flagged_out", default="data/failures/validate_flagged.jsonl")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.inp).read_text(encoding="utf-8").splitlines() if l.strip()]
    n = len(rows)

    code_counts = Counter()
    flagged = []
    attendee_freq = Counter()
    msg_seen = Counter()
    cls_count = Counter()

    for i, r in enumerate(rows):
        issues = check_row(i, r)
        if issues:
            code_counts.update(c for c, _ in issues)
            flagged.append({"line": i + 1, "scenario_id": r.get("scenario_id"),
                            "issues": issues, "message": (r.get("message") or "")[:80],
                            "gold": r.get("gold")})
        gold = r.get("gold", {})
        cls_count[gold.get("has_schedule")] += 1
        for ev in gold.get("events", []) or []:
            for a in ev.get("attendees") or []:
                attendee_freq[a] += 1
        msg_seen[(r.get("message") or "").strip()] += 1

    print(f"=== 전수 검증: {n}행 ===")
    print(f"3-way: yes {cls_count['yes']} · pending {cls_count['pending']} · no {cls_count['no']} "
          f"(no비 {cls_count['no']/n:.1%})")
    dups = {m: c for m, c in msg_seen.items() if c > 1 and m}
    print(f"중복 메시지: {len(dups)}종 (총 {sum(c-1 for c in dups.values())}건 잉여)")
    print(f"결함 보유 행: {len(flagged)}/{n} = {len(flagged)/n:.1%}")
    print("\n--- 결함 코드별 건수 ---")
    for code, cnt in code_counts.most_common():
        print(f"  {cnt:5d}  {code}")
    print("\n--- attendee 상위 15 (편향=포이즌닝 점검; 메모리: 민준 사건) ---")
    total_at = sum(attendee_freq.values())
    for name, cnt in attendee_freq.most_common(15):
        print(f"  {cnt:5d}  ({cnt/max(1,total_at):.1%})  {name}")
    print(f"  attendee 토큰 총 {total_at}개 / 고유 {len(attendee_freq)}종")

    Path(args.flagged_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.flagged_out, "w", encoding="utf-8") as f:
        for r in flagged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[flagged] {len(flagged)}건 → {args.flagged_out}")


if __name__ == "__main__":
    main()
