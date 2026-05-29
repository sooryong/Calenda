"""금/토/일 발신 + 상대날짜(내일/모레/글피) 주말-횡단 학습 샘플 생성기.

배경: round2(v2) 모델이 금요일 "내일"을 주말 건너뛴 다음 평일로 잘못 계산함.
원인은 학습/평가셋에 '주말을 가로지르는 상대날짜' 케이스가 없던 것.
이 스크립트는 **날짜 계산을 결정론적으로** 수행해 gold 라벨이 항상 정확하도록 보장한다
(LLM 생성보다 이 케이스에선 더 안전 — 라벨 오류 0). 유료 API 미사용.

출력: data/processed/weekend_boost.jsonl
사용: python scripts/gen_weekend_boost.py --n 150 [--seed 7]
이후 train.jsonl에 합치려면 --append-to data/processed/train.jsonl
"""
from __future__ import annotations
import argparse, json, random
from datetime import date, datetime, timedelta

WD = ["월", "화", "수", "목", "금", "토", "일"]
REL = [("내일", 1, 0.55), ("모레", 2, 0.30), ("글피", 3, 0.15)]
TIMES = [
    ("아침 8시", 8, 0), ("오전 9시", 9, 0), ("오전 10시", 10, 0), ("오전 10시 반", 10, 30),
    ("오전 11시", 11, 0), ("낮 12시", 12, 0), ("정오", 12, 0), ("오후 1시", 13, 0),
    ("오후 2시", 14, 0), ("오후 2시 반", 14, 30), ("오후 3시", 15, 0), ("오후 4시", 16, 0),
    ("오후 5시", 17, 0), ("오후 6시", 18, 0), ("저녁 7시", 19, 0), ("저녁 7시 반", 19, 30),
    ("저녁 8시", 20, 0), ("밤 9시", 21, 0),
]

FRIENDS = ["민수", "지훈", "서연", "하늘", "예진", "도윤", "수아", "건우", "유진", "태현"]
MEET = ["강남역 11번 출구", "홍대입구역 2번 출구", "서울숲 정문", "합정 스타벅스",
        "잠실역 8번 출구", "연남동 카페", "여의도 한강공원", "성수동 카페거리"]
RESTAURANTS = ["강남 한정식집", "연남동 막걸리집", "이태원 타코집", "건대 곱창집", "성수동 파스타집"]
CLINICS = ["튼튼치과", "서울내과", "맑은눈안과", "행복정형외과", "미소피부과"]
SVCS = ["스케일링", "정기검진", "진료", "물리치료", "건강검진"]
ACTS = ["등산", "러닝", "풋살", "요가 클래스", "독서 모임", "사진 출사", "플로깅"]
ACT_PLACES = ["관악산 입구", "올림픽공원", "한강 반포지구", "북한산 우이역", "양재천 산책로"]
TOPICS = ["주간 회의", "프로젝트 킥오프", "리뷰 미팅", "발표 리허설", "스프린트 플래닝"]
WORK_PLACES = ["회의실 A", "3층 대회의실", "본사 로비", "줌(온라인)", "구글밋"]
ONLINE = {"줌(온라인)", "구글밋"}


def _rel(rng):
    r = rng.random(); acc = 0
    for word, off, w in REL:
        acc += w
        if r <= acc:
            return word, off
    return REL[0][0], REL[0][1]


def _event(title, start, location, attendees, description, conf):
    return {"title": title, "start": start, "end": None, "all_day": False,
            "location": location, "attendees": attendees, "description": description,
            "recurrence": None, "confidence": conf}


def make_record(rng, idx, base_d):
    rel_word, off = _rel(rng)
    tgt = base_d + timedelta(days=off)
    ttext, hh, mm = rng.choice(TIMES)
    start = f"{tgt.isoformat()}T{hh:02d}:{mm:02d}:00+09:00"
    recv_h = rng.randint(8, 22)
    received_at = f"{base_d.isoformat()}T{recv_h:02d}:{rng.choice([0,15,30,45]):02d}:00+09:00"
    kind = rng.choice(["friend", "meal", "clinic", "club", "work"])

    if kind == "friend":
        f = rng.choice(FRIENDS); loc = rng.choice(MEET)
        msg = rng.choice([
            f"{rel_word} {ttext}에 {loc}에서 보자~",
            f"야 {rel_word} {ttext} {loc} 어때?",
            f"{rel_word} {ttext}에 {loc} ㄱㄱ",
        ])
        ev = _event(f"{f}와 약속", start, loc, [f], None, round(rng.uniform(0.85, 0.92), 2))
        return dict(channel="kakao", sender=f, message=msg, gold_event=ev)

    if kind == "meal":
        f = rng.choice(FRIENDS); loc = rng.choice(RESTAURANTS)
        msg = rng.choice([
            f"{rel_word} {ttext} {loc}에서 같이 밥 먹자",
            f"{rel_word} {ttext}에 {loc} 예약했어! 늦지마",
        ])
        ev = _event(f"{f}와 식사", start, loc, [f], None, round(rng.uniform(0.85, 0.93), 2))
        return dict(channel="kakao", sender=f, message=msg, gold_event=ev)

    if kind == "clinic":
        c = rng.choice(CLINICS); svc = rng.choice(SVCS)
        phone = f"02-{rng.randint(200,999)}-{rng.randint(1000,9999)}"
        msg = f"[{c}] {rel_word} {ttext} {svc} 예약 안내드립니다. 변경/취소 {phone}."
        ev = _event(f"{svc}: {c}", start, c, [], f"변경/취소: {phone}", round(rng.uniform(0.93, 0.98), 2))
        return dict(channel="sms", sender=f"[Web발신] {c}", message=msg, gold_event=ev)

    if kind == "club":
        a = rng.choice(ACTS); loc = rng.choice(ACT_PLACES)
        msg = rng.choice([
            f"{rel_word} {ttext} {a} 모임 있습니다. {loc} 집합!",
            f"공지) {rel_word} {ttext} {a} 모임 — 장소: {loc}",
        ])
        ev = _event(f"{a} 모임", start, loc, [], None, round(rng.uniform(0.86, 0.92), 2))
        return dict(channel="kakao", sender=f"{a}모임", message=msg, gold_event=ev)

    # work
    t = rng.choice(TOPICS); wp = rng.choice(WORK_PLACES)
    online = wp in ONLINE
    place_txt = wp
    msg = rng.choice([
        f"{rel_word} {ttext} {t} 진행합니다. 장소: {place_txt}",
        f"팀 여러분, {rel_word} {ttext}부터 {t} 있습니다 ({place_txt}).",
    ])
    ev = _event(t, start, None if online else wp, [], (wp if online else None),
                round(rng.uniform(0.88, 0.95), 2))
    return dict(channel=rng.choice(["kakao", "gmail"]), sender=rng.choice(["팀장", "매니저", "PM"]),
                message=msg, gold_event=ev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/processed/weekend_boost.jsonl")
    ap.add_argument("--append-to", default=None, help="추가로 합칠 학습 파일 (예: data/processed/train.jsonl)")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # 주말-횡단 강조: 금(4)/토(5)/일(6) 발신만 사용
    pool = []
    d = date(2026, 6, 1)
    while d <= date(2026, 12, 31):
        if d.weekday() in (4, 5, 6):
            pool.append(d)
        d += timedelta(days=1)

    records = []
    for i in range(args.n):
        base_d = rng.choice(pool)
        r = make_record(rng, i, base_d)
        ev = r["gold_event"]
        rec = {
            "scenario_id": f"weekend_rel_{i:03d}",
            "received_at": f"{base_d.isoformat()}T{rng.randint(8,22):02d}:00:00+09:00",
            "channel": r["channel"], "sender": r["sender"], "language": "ko",
            "message": r["message"],
            "gold": {"has_schedule": True, "events": [ev]},
        }
        # received_at 시각을 make_record와 분리해 재설정했으니 여기서 통일 불필요(위에서 이미 base_d 사용)
        records.append(rec)

    # --- 검증: 라벨 정확성 (received 요일 + 오프셋 == start 날짜) ---
    bad = 0
    wcross = 0
    for rec in records:
        rd = datetime.fromisoformat(rec["received_at"]).date()
        sd = datetime.fromisoformat(rec["gold"]["events"][0]["start"]).date()
        off = (sd - rd).days
        msg = rec["message"]
        exp = 1 if "내일" in msg else 2 if "모레" in msg else 3 if "글피" in msg else None
        if exp is None or off != exp:
            bad += 1
        # 주말 횡단 = received와 start 사이에 토/일이 끼는지
        if any((rd + timedelta(days=k)).weekday() in (5, 6) for k in range(1, off + 1)):
            wcross += 1
    assert bad == 0, f"{bad} records have wrong relative-date labels!"

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records -> {args.out}  (weekend-crossing: {wcross}, label errors: {bad})")

    if args.append_to:
        with open(args.append_to, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"appended {len(records)} records -> {args.append_to}")


if __name__ == "__main__":
    main()
