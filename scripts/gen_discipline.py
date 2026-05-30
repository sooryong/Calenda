"""round7 추출 디시플린 보강 (새 스키마 직접 emit).

r6 실패 분석에서 나온 3개 추출 오류를 겨냥:
  1) has_schedule 오탐: 제안/질문/막연/취소(날짜·시각 있어도 일정 아님) → 음성
  2) time.marker 환각: 표시어 없는 "N시"엔 marker=null로 둬야 (모델이 '오전'을 환각함)
  3) date 토큰 어휘: 다양한 상대표현 → 올바른 한국어 토큰

출력: data/processed/discipline_boost.jsonl
유료 API 미사용, 라벨은 구성상 정확.
"""
from __future__ import annotations
import argparse, json, random
from datetime import date, timedelta

# (메시지 표면형, gold date 토큰)
DATES = [
    ("오늘", "오늘"), ("내일", "내일"), ("모레", "모레"), ("글피", "글피"),
    ("3일 뒤", "3일후"), ("5일 뒤", "5일후"), ("일주일 뒤", "1주후"), ("2주 뒤", "2주후"),
    ("다음 주", "다음주"), ("다음 주 화요일", "다음주화"), ("다음 주 금요일", "다음주금"),
    ("이번 주 토요일", "이번주토"), ("한 달 뒤", "1개월후"), ("이번 주말", "이번주말"), ("다음 주말", "다음주말"),
]
# 표시어 있는 시각 (표면, hour, minute, marker)
TIMES_MARKED = [
    ("오전 9시", 9, 0, "오전"), ("오전 11시", 11, 0, "오전"), ("낮 12시", 12, 0, "낮"),
    ("정오", 12, 0, "정오"), ("오후 2시", 2, 0, "오후"), ("오후 3시 반", 3, 30, "오후"),
    ("오후 5시", 5, 0, "오후"), ("저녁 7시", 7, 0, "저녁"), ("저녁 8시", 8, 0, "저녁"),
    ("밤 9시", 9, 0, "밤"), ("아침 8시", 8, 0, "아침"),
]
# 표시어 없는 맨 시각 (표면, hour, minute) → gold marker=null
TIMES_BARE = [(f"{h}시", h, 0) for h in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11)] + \
             [(f"{h}시 반", h, 30) for h in (3, 6, 7, 8)]

FRIENDS = ["민수", "지훈", "서연", "하늘", "예진", "도윤", "수아", "건우", "유진"]
LEADS = ["이팀장", "박과장", "최선임", "김매니저"]
PLACES = ["강남역 11번 출구", "홍대입구역 2번 출구", "서울숲 정문", "합정 스타벅스", "잠실역 8번 출구",
          "연남동 카페", "회의실 A", "회의실 B", "강남 한정식집", "성수동 파스타집"]
ACTS_SOCIAL = ["약속", "저녁식사", "점심", "스터디", "모임", "커피챗"]
ACTS_WORK = ["주간 회의", "코드 리뷰", "기획 미팅", "리뷰 미팅"]


def _ev(title, date_tok, h, m, marker, loc, att, conf):
    return {"title": title, "date": date_tok,
            "time": {"hour": h, "minute": m, "marker": marker},
            "end_time": None, "all_day": False, "location": loc,
            "attendees": att, "organizer": None, "description": None,
            "recurrence": None, "confidence": conf}


def make_positive(rng, bare: bool):
    """bare=True면 marker 없는 맨 시각(marker=null), False면 표시어 있는 시각."""
    dsurf, dtok = rng.choice(DATES)
    work = rng.random() < 0.4
    other = rng.choice(LEADS if work else FRIENDS)
    act = rng.choice(ACTS_WORK if work else ACTS_SOCIAL)
    place = rng.choice(PLACES)
    if bare:
        tsurf, h, m = rng.choice(TIMES_BARE)
        marker = None
    else:
        tsurf, h, m, marker = rng.choice(TIMES_MARKED)
    msg = rng.choice([
        f"{dsurf} {tsurf}에 {place}에서 {act}",
        f"{dsurf} {tsurf} {act} 잡았어요. 장소는 {place}",
        f"{dsurf} {tsurf}에 {place}에서 보자",
    ])
    att = [] if work else [other]
    ev = _ev(act, dtok, h, m, marker, place, att, round(rng.uniform(0.86, 0.94), 2))
    return dict(channel="kakao", sender=other, message=msg, gold_event=ev)


def make_negative(rng):
    """날짜·시각 단서는 있으나 일정 아님(제안/질문/막연/취소) → has_schedule=false."""
    dsurf, _ = rng.choice(DATES)
    other = rng.choice(FRIENDS + LEADS)
    act = rng.choice(ACTS_SOCIAL + ACTS_WORK)
    place = rng.choice(PLACES)
    tsurf = rng.choice([t[0] for t in TIMES_MARKED] + [t[0] for t in TIMES_BARE])
    kind = rng.choices(["question", "vague", "cancel"], weights=[0.45, 0.3, 0.25])[0]
    if kind == "question":
        msg = rng.choice([
            f"{dsurf} {tsurf} {act} 어때요?",
            f"혹시 {dsurf} {tsurf}에 {place} 가능해요?",
            f"{dsurf} {act} 시간 돼?",
            f"{dsurf} {tsurf}쯤 괜찮으세요?",
        ])
    elif kind == "vague":
        msg = rng.choice([
            f"조만간 {act} 한번 보자~",
            f"{dsurf} 시간 되면 {act} 하자",
            f"{act}, 다음에 날 잡읍시다",
        ])
    else:
        msg = rng.choice([
            f"{dsurf} {act} 못 갈 것 같아 ㅠㅠ",
            f"미안 {dsurf} {tsurf} 약속 취소해야 할 듯",
            f"{dsurf} {place} {act} 취소됐어요",
        ])
    return dict(channel=rng.choice(["kakao", "kakao", "sms"]), sender=other, message=msg, gold_event=None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", default="data/processed/discipline_boost.jsonl")
    ap.add_argument("--append-to", default=None)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    pool = []
    d = date(2026, 6, 1)
    while d <= date(2026, 12, 31):
        pool.append(d)
        d += timedelta(days=1)

    records, npos_bare, npos_mark, nneg = [], 0, 0, 0
    for i in range(args.n):
        r = rng.random()
        base_d = rng.choice(pool)
        recv = f"{base_d.isoformat()}T{rng.randint(8, 21):02d}:{rng.choice([0,30]):02d}:00+09:00"
        if r < 0.40:                       # 음성
            g = make_negative(rng); nneg += 1
            gold = {"has_schedule": False, "events": []}
        elif r < 0.70:                     # 맨시각 양성
            g = make_positive(rng, bare=True); npos_bare += 1
            gold = {"has_schedule": True, "events": [g["gold_event"]]}
        else:                              # 표시어 양성
            g = make_positive(rng, bare=False); npos_mark += 1
            gold = {"has_schedule": True, "events": [g["gold_event"]]}
        records.append({
            "scenario_id": f"discipline_{i:03d}", "received_at": recv,
            "channel": g["channel"], "sender": g["sender"], "language": "ko",
            "message": g["message"], "gold": gold,
        })

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} -> {args.out}  (음성 {nneg} / 맨시각양성 {npos_bare} / 표시어양성 {npos_mark})")

    if args.append_to:
        with open(args.append_to, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"appended {len(records)} -> {args.append_to}")


if __name__ == "__main__":
    main()
