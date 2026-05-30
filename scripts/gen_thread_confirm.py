"""멀티턴 '대화로 확정되는 일정' 학습 샘플 생성기.

배경: 일정이 단일 메시지가 아니라 여러 메시지를 주고받으며 확정되는 경우가 많다.
이 스크립트는 thread_context(이전 대화) + 확정 message + 최종 합의 gold 페어를 생성한다.
핵심: 협의 중 시간/장소/날짜가 '바뀌는' 케이스에서 gold가 항상 **최종 합의값**을 반영하도록
      파라미터(최종 offset/시각/장소)를 단일 소스로 두고 거기서 gold와 대화 텍스트를 함께 만든다.
      → 라벨 오류 0 (LLM 생성보다 안전). 유료 API 미사용.

입력 포맷은 _common.build_user_block의 <대화내역> 블록과 일치한다.
출력: data/processed/thread_confirm.jsonl
"""
from __future__ import annotations
import argparse, json, random
from datetime import date, datetime, timedelta

WD = ["월", "화", "수", "목", "금", "토", "일"]
REL = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}
TIMES = [
    ("오전 9시", 9, 0), ("오전 10시", 10, 0), ("오전 11시", 11, 0), ("낮 12시", 12, 0),
    ("오후 1시", 13, 0), ("오후 2시", 14, 0), ("오후 3시", 15, 0), ("오후 4시", 16, 0),
    ("오후 5시", 17, 0), ("오후 6시", 18, 0), ("저녁 7시", 19, 0), ("저녁 8시", 20, 0),
]
FRIENDS = ["민수", "지훈", "서연", "하늘", "예진", "도윤", "수아", "건우"]
LEADS = ["이팀장", "박과장", "최선임", "김매니저"]
MEET = ["강남역 11번 출구", "홍대입구역 2번 출구", "서울숲 정문", "합정 스타벅스", "잠실역 8번 출구"]
ROOMS = ["회의실 A", "회의실 B", "3층 대회의실", "줌(온라인)", "구글밋"]
ONLINE = {"줌(온라인)", "구글밋"}
ACTS = ["코드 리뷰", "주간 회의", "점심", "저녁 약속", "스터디", "기획 미팅"]


def _two(rng, pool):
    a = rng.choice(pool)
    b = rng.choice([x for x in pool if x != a])
    return a, b


def _gwa(word: str) -> str:
    """받침 유무에 따라 '와/과' 선택 (예: 지훈→과, 서연→과, 민수→와... 한글 종성 기준)."""
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "과" if (ord(ch) - 0xAC00) % 28 else "와"
    return "와"


def _ev(title, start, location, attendees, desc, conf):
    return {"title": title, "start": start, "end": None, "all_day": False,
            "location": location, "attendees": attendees, "description": desc,
            "recurrence": None, "confidence": conf}


def make(rng, base_d, neg_ratio=0.35):
    """하나의 멀티턴 레코드 (thread_context + message + gold) 생성.
    neg_ratio 확률로 '미확정'(최종 메시지가 새 제안/유보 → has_schedule=false) 케이스 생성."""
    other = rng.choice(FRIENDS + LEADS)
    is_work0 = other in LEADS
    if rng.random() < neg_ratio:
        # --- 미확정(negative): 대화는 오갔지만 아직 확정 안 됨 ---
        act_n = rng.choice(["주간 회의", "리뷰 미팅"]) if is_work0 else rng.choice(["저녁", "점심", "약속"])
        rel_n = rng.choice(["내일", "모레", "이번 주말"])
        tt, _, _ = rng.choice(TIMES)
        base_hh = rng.choice([10, 11, 13, 14])
        thread = [{"time": f"{base_hh-1:02d}:30", "sender": other, "message": f"{rel_n} {act_n} 어때요?"}]
        final = rng.choice([
            f"{tt}는 어떠세요?",                 # 역제안
            "음 일정 확인하고 알려드릴게요",        # 유보
            "장소는 좀 더 생각해볼게요",            # 일부 미정
            "가능한지 좀 봐야 할 것 같아요",
        ])
        return {
            "received_at": f"{base_d.isoformat()}T{base_hh:02d}:00:00+09:00",
            "channel": "kakao", "sender": "나", "language": "ko",
            "thread_context": thread, "message": final,
            "gold": {"has_schedule": False, "events": []},
        }

    shape = rng.choice(["simple", "time_change", "place_change", "date_change", "buildup"])
    is_work = other in LEADS
    act = rng.choice(["주간 회의", "코드 리뷰", "기획 미팅"]) if is_work else rng.choice(["점심", "저녁 약속", "스터디", "약속"])
    place_pool = ROOMS if is_work else MEET
    base_hh, base_mm = rng.choice([(10, 0), (10, 30), (11, 0), (13, 0), (14, 0)])
    recv = f"{base_d.isoformat()}T{base_hh:02d}:{base_mm:02d}:00+09:00"
    t0 = f"{max(base_hh-1,8):02d}:{rng.choice([5,15,25]):02d}"
    t1 = f"{max(base_hh-1,8):02d}:{rng.choice([35,45,55]):02d}"

    def title():
        if is_work:
            return f"{act}, {place}" if place not in ONLINE else act
        return f"{other}{_gwa(other)} {act}"

    if shape == "simple":
        rel = rng.choice(["내일", "모레", "글피"]); off = REL[rel]
        ttext, hh, mm = rng.choice(TIMES); place = rng.choice(place_pool)
        thread = [{"time": t0, "sender": other, "message": f"{rel} {ttext}에 {place}에서 {act} 어때요?"}]
        msg = rng.choice([f"좋아요 {rel} {ttext} {place}", f"네 {rel} {ttext} {place}에서 봬요"])

    elif shape == "time_change":
        rel = rng.choice(["내일", "모레", "글피"]); off = REL[rel]
        i, j = rng.sample(range(len(TIMES)), 2)
        t1text = TIMES[i][0]               # 변경 전(거절된) 시각
        ttext, hh, mm = TIMES[j]           # 최종 합의 시각
        place = rng.choice(place_pool)
        thread = [
            {"time": t0, "sender": other, "message": f"{rel} {t1text}에 {place} {act} 가능해요?"},
            {"time": t1, "sender": "나", "message": f"{t1text}은 좀 어렵고 {ttext}는 어떨까요?"},
            {"time": f"{base_hh-0:02d}:{max(base_mm-2,0):02d}", "sender": other, "message": f"네 {ttext} 좋아요"},
        ]
        msg = f"그럼 {rel} {ttext} {place}로 확정할게요"  # 최종=ttext(hh,mm)

    elif shape == "place_change":
        rel = rng.choice(["내일", "모레", "글피"]); off = REL[rel]
        ttext, hh, mm = rng.choice(TIMES)
        p1, place = _two(rng, place_pool)
        thread = [
            {"time": t0, "sender": other, "message": f"{rel} {ttext} {p1}에서 {act} 할까요?"},
            {"time": t1, "sender": "나", "message": f"{p1} 말고 {place} 어때요?"},
            {"time": f"{base_hh:02d}:{max(base_mm-1,0):02d}", "sender": other, "message": f"{place} 좋죠"},
        ]
        msg = f"{rel} {ttext} {place}에서 봬요"  # 최종 장소=place

    elif shape == "date_change":
        r1, r2 = _two(rng, ["내일", "모레", "글피"]); off = REL[r2]
        ttext, hh, mm = rng.choice(TIMES); place = rng.choice(place_pool)
        thread = [
            {"time": t0, "sender": other, "message": f"{r1} {ttext}에 {act} 어때요?"},
            {"time": t1, "sender": "나", "message": f"{r1}은 안 되고 {r2} 가능할까요?"},
            {"time": f"{base_hh:02d}:{max(base_mm-1,0):02d}", "sender": other, "message": f"{r2} 괜찮아요"},
        ]
        msg = f"{r2} {ttext} {place} 확정이요"  # 최종 날짜=r2

    else:  # buildup: 시간/장소가 대화에 흩어져 있고 최종 메시지는 마지막 조각만
        rel = rng.choice(["내일", "모레", "글피"]); off = REL[rel]
        ttext, hh, mm = rng.choice(TIMES); place = rng.choice(place_pool)
        thread = [
            {"time": t0, "sender": other, "message": f"{rel} {act} 하실래요?"},
            {"time": f"{max(base_hh-1,8):02d}:{rng.choice([20,30])}", "sender": "나", "message": "몇 시가 좋아요?"},
            {"time": t1, "sender": other, "message": f"{ttext} 어때요?"},
            {"time": f"{base_hh:02d}:{max(base_mm-1,0):02d}", "sender": "나", "message": "좋아요 어디서?"},
        ]
        msg = f"{place}에서 봬요"  # 시간은 thread, 장소는 최종 메시지

    start = f"{(base_d + timedelta(days=off)).isoformat()}T{hh:02d}:{mm:02d}:00+09:00"
    online = place in ONLINE
    ev = _ev(title(), start, None if online else place, ([] if is_work else [other]),
             ("스레드 협의 확정" + (f" / {place}" if online else "")), round(rng.uniform(0.88, 0.95), 2))
    return {
        "received_at": recv, "channel": "kakao", "sender": "나", "language": "ko",
        "thread_context": thread, "message": msg,
        "gold": {"has_schedule": True, "events": [ev]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="data/processed/thread_confirm.jsonl")
    ap.add_argument("--append-to", default=None)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # 날짜 풀: 주말 횡단도 섞이도록 전 요일 사용(금/토 가중)
    pool = []
    d = date(2026, 6, 1)
    while d <= date(2026, 12, 31):
        reps = 2 if d.weekday() in (4, 5) else 1
        pool += [d] * reps
        d += timedelta(days=1)

    records = []
    for i in range(args.n):
        rec = make(rng, rng.choice(pool))
        rec["scenario_id"] = f"thread_confirm_{i:03d}"
        records.append(rec)

    # --- 검증: 날짜 라벨이 최종 메시지/대화의 상대표현과 일치하는지 (positive만) ---
    bad = []
    for rec in records:
        ev = rec["gold"]["events"]
        if not ev:  # 미확정(negative)은 날짜 검증 대상 아님
            continue
        rd = datetime.fromisoformat(rec["received_at"]).date()
        sd = datetime.fromisoformat(ev[0]["start"]).date()
        off = (sd - rd).days
        # 최종 합의 상대표현은 message에 있거나(대부분) date_change는 message의 r2
        txt = rec["message"]
        # buildup은 message에 rel이 없을 수 있음 → thread 첫 턴의 rel 사용
        rels_in = [w for w in REL if w in txt] or [w for w in REL if any(w in t["message"] for t in rec["thread_context"])]
        exp = REL[rels_in[-1]] if rels_in else None
        if exp is None or off != exp:
            bad.append((rec["scenario_id"], off, exp, txt))
    if bad:
        for b in bad[:10]:
            print("LABEL MISMATCH:", b)
        raise SystemExit(f"{len(bad)} label mismatches — 생성 로직 점검 필요")

    neg = sum(1 for r in records if not r["gold"]["events"])
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} -> {args.out}  (확정 {len(records)-neg} / 미확정 {neg}, label errors: 0)")

    if args.append_to:
        with open(args.append_to, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"appended {len(records)} -> {args.append_to}")


if __name__ == "__main__":
    main()
