"""상대 날짜 표현의 gold.start/end 날짜를 결정론적으로 재계산해 교정.

문제: 합성 데이터의 상대 요일 표현(이번주/다음주 X요일 등)이 잘못된 날짜로
라벨링됨 (검증에서 '이번주 X요일' 71% 오류). 모델이 이를 학습해 요일 계산 실패.

해결: 메시지에서 상대 날짜 표현을 파싱 → received_at 기준으로 정확한 날짜 산출 →
gold.start/end의 '날짜 부분만' 교체 (시각·타임존은 유지).

보수적 원칙:
- 메시지에 절대 날짜(M월 D일, YYYY.MM.DD, M/D)가 있으면 그게 우선 → 상대 교정 안 함
- 명확히 파싱되는 패턴만 교정. 애매하면 건드리지 않음
- has_schedule=false 또는 events 없으면 skip

사용:
    python scripts/fix_relative_dates.py --in data/raw/v1.jsonl --out data/raw/v1.jsonl
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta

import orjson

WD = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# 절대 날짜가 메시지에 있으면 상대 교정 skip
ABS_DATE_RE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{1,2}\s*/\s*\d{1,2}")

# 상대 표현 패턴
THIS_WEEK_WD = re.compile(r"이번\s*주\s*([월화수목금토일])\s*요일")
NEXT_WEEK_WD = re.compile(r"(?:다음\s*주|담주|다음주)\s*([월화수목금토일])\s*요일")
WEEK_AFTER_WD = re.compile(r"다다음\s*주\s*([월화수목금토일])\s*요일")
TOMORROW = re.compile(r"내일")
DAY_AFTER = re.compile(r"모레")
TWO_DAYS_AFTER = re.compile(r"글피")
TODAY = re.compile(r"오늘|본일|당일|금일")
N_DAYS_LATER = re.compile(r"(\d+)\s*일\s*(?:후|뒤|있다가|이따)")


def parse_dt(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def iso_week_monday(d: datetime) -> datetime:
    return d - timedelta(days=d.weekday())


def compute_target_date(recv: datetime, msg: str):
    """메시지의 상대 표현 → 목표 date. 못 찾으면 None. (date만, 시각 무시)"""
    recv_d = recv.date()

    m = WEEK_AFTER_WD.search(msg)
    if m:
        monday = iso_week_monday(recv) + timedelta(weeks=2)
        return (monday + timedelta(days=WD[m.group(1)])).date()

    m = NEXT_WEEK_WD.search(msg)
    if m:
        monday = iso_week_monday(recv) + timedelta(weeks=1)
        return (monday + timedelta(days=WD[m.group(1)])).date()

    m = THIS_WEEK_WD.search(msg)
    if m:
        monday = iso_week_monday(recv)
        return (monday + timedelta(days=WD[m.group(1)])).date()

    m = N_DAYS_LATER.search(msg)
    if m:
        return (recv + timedelta(days=int(m.group(1)))).date()

    if TWO_DAYS_AFTER.search(msg):
        return (recv + timedelta(days=3)).date()
    if DAY_AFTER.search(msg):
        return (recv + timedelta(days=2)).date()
    if TOMORROW.search(msg):
        return (recv + timedelta(days=1)).date()
    if TODAY.search(msg):
        return recv_d
    return None


def replace_date_keep_time(iso_dt: str, new_date) -> str:
    """ISO datetime 문자열의 날짜 부분만 new_date로 교체, 시각·tz 유지."""
    dt = parse_dt(iso_dt)
    if dt is None:
        return iso_dt
    new_dt = dt.replace(year=new_date.year, month=new_date.month, day=new_date.day)
    return new_dt.isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    with open(args.inp, "rb") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(orjson.loads(line))

    n_total = len(rows)
    n_checked = 0
    n_fixed = 0
    fixed_examples = []

    for r in rows:
        gold = r.get("gold") or {}
        if not gold.get("has_schedule"):
            continue
        events = gold.get("events") or []
        if not events:
            continue
        msg = r.get("message", "")
        recv = parse_dt(r.get("received_at", ""))
        if recv is None:
            continue
        # 절대 날짜 있으면 skip (절대 우선)
        if ABS_DATE_RE.search(msg):
            continue
        target = compute_target_date(recv, msg)
        if target is None:
            continue
        n_checked += 1

        # 첫 이벤트 기준으로 날짜 교정 (multi-event는 동일 날짜 가정 — 보수적으로 첫 건만)
        ev = events[0]
        old_start = ev.get("start")
        if not old_start or not isinstance(old_start, str):
            continue
        old_date = parse_dt(old_start)
        if old_date is None:
            continue
        if old_date.date() == target:
            continue  # 이미 정확

        new_start = replace_date_keep_time(old_start, target)
        if len(fixed_examples) < 12:
            fixed_examples.append((r.get("received_at", "")[:10], msg[:40], old_start[:10], new_start[:10]))
        ev["start"] = new_start
        if ev.get("end") and isinstance(ev["end"], str):
            ev["end"] = replace_date_keep_time(ev["end"], target)
        n_fixed += 1

    with open(args.out, "wb") as f:
        for r in rows:
            f.write(orjson.dumps(r))
            f.write(b"\n")

    print(f"총 {n_total}건, 상대표현 검사 {n_checked}건, 날짜 교정 {n_fixed}건")
    print()
    print("교정 예시 (received | msg | old → new):")
    for recv, msg, old, new in fixed_examples:
        print(f"  {recv} | {msg:40} | {old} → {new}")


if __name__ == "__main__":
    main()
