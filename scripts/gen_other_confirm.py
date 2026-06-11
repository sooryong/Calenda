"""멀티턴 하드케이스 — '상대가 맨 「네」로 확정, 일정 값은 내 이전 메시지에 있음'.

배경(실패 케이스, 박상로 카톡):
  나:    "금요일 10시 경북대 복지관 할리스카페"   ← 구체 일정은 내 메시지
  상대:  "네"                                   ← 최종 메시지는 상대의 맨 확정
앱이 "네"를 트리거로 추출하는데, 기존 thread_confirm 학습은 **최종 메시지가 sender="나"이고
값을 재진술**하는 형태뿐이라(분포 밖) 0.5B가 날짜를 환각했다(다음주화/6-29).

이 생성기는 그 변형을 채운다:
  - 최종 message = 상대의 짧은 확정("네"/"네 좋습니다"/"그때 뵙겠습니다"…), sender=상대.
  - 일정 값(날짜·시각·장소)은 thread_context의 [나] 메시지에 있음.
  - gold = 내가 제안한 값 (★ 신스키마: date 토큰 + time 객체 — train.jsonl과 동일).
  - 음성도 섞음: "네"가 일정이 아니라 '주소/자료 보내달라'에 대한 응답인 케이스 → has_schedule:false
    (박상로 대화의 '찾아갈 주소 → 네' 턴처럼, 모든 "네"에 발화하지 않도록 변별 학습).

라벨 정확성: 날짜 토큰은 _common.resolve_date로 의도 날짜와 일치 검증(라벨오류 0, 유료 API 미사용).
출력: data/processed/r23_hardcases.jsonl   사용: python scripts/gen_other_confirm.py [--apply]
"""
from __future__ import annotations
import argparse, json, random, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import resolve_date  # 라벨 검증용(앱 DateResolver의 미러)

WD = ["월", "화", "수", "목", "금", "토", "일"]
# (surface, hour12, minute, marker) — gold.time과 동일 표기. marker로 AM/PM 구분.
TIMES = [
    ("오전 9시", 9, 0, "오전"), ("오전 10시", 10, 0, "오전"), ("오전 11시", 11, 0, "오전"),
    ("낮 12시", 12, 0, "낮"), ("오후 1시", 1, 0, "오후"), ("오후 2시", 2, 0, "오후"),
    ("오후 3시", 3, 0, "오후"), ("오후 4시", 4, 0, "오후"), ("오후 5시", 5, 0, "오후"),
    ("저녁 6시", 6, 0, "저녁"), ("저녁 7시", 7, 0, "저녁"), ("10시", 10, 0, None),
    ("2시", 2, 0, None), ("3시", 3, 0, None),
]
OTHERS = ["박상로", "김교수님", "이대표", "최팀장", "정선생님", "한과장", "오대리", "윤원장님"]
ACTS_1on1 = ["멘토링", "미팅", "상담", "점심", "저녁", "면담", "커피챗", "인터뷰"]
PLACES = [
    ("경북대 복지관 할리스카페", "할리스 쿱카페 경북대 크누라운지점 대구 북구 대학로 80 복지관"),
    ("강남역 스타벅스", None), ("판교역 1번 출구", None), ("코엑스 3층 카페", None),
    ("시청 앞 투썸", None), ("회사 1층 로비", None), ("동성로 엔제리너스", None),
    ("범어역 2번 출구", None),
]
# 상대의 짧은 확정(최종 메시지) — 값 재진술 없음.
CONFIRMS = ["네", "네 좋습니다", "네 그때 뵙겠습니다", "확인했습니다", "그렇게 하시죠",
            "넵 알겠습니다", "네 그때 봬요", "좋습니다 그때 뵐게요", "예 알겠습니다"]


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_token(recv: date, target_wd: int) -> tuple[str, date]:
    """맨 요일('금요일')의 정규 토큰(이번주X/다음주X) + 실제 날짜. 다가오는 그 요일(오늘 포함)."""
    days_ahead = (target_wd - recv.weekday()) % 7
    upcoming = recv + timedelta(days=days_ahead)
    this_week = monday_of(recv) + timedelta(days=target_wd)
    prefix = "이번주" if upcoming == this_week else "다음주"
    return prefix + WD[target_wd], upcoming


def pick_date(rng, recv: date):
    """(surface_in_message, gold_date_token, intended_date) 반환."""
    kind = rng.choice(["offset", "offset", "bareWD", "bareWD", "prefixWD"])
    if kind == "offset":
        s, off = rng.choice([("내일", 1), ("모레", 2), ("글피", 3)])
        return s, s, recv + timedelta(days=off)
    target = rng.choice([0, 1, 2, 3, 4])  # 월~금 위주(주말 약속도 가끔)
    tok, d = week_token(recv, target)
    if kind == "bareWD":
        return f"{WD[target]}요일", tok, d   # 메시지엔 맨 '금요일', gold엔 정규 토큰
    # prefixWD: 메시지도 '이번 주 금요일' / '다음 주 화요일'
    pre = "이번 주" if tok.startswith("이번주") else "다음 주"
    return f"{pre} {WD[target]}요일", tok, d


def make_pos(rng, recv: date) -> dict:
    other = rng.choice(OTHERS)
    act = rng.choice(ACTS_1on1)
    surf_d, tok_d, intended = pick_date(rng, recv)
    ttext, hh, mm, marker = rng.choice(TIMES)
    place_disp, addr = rng.choice(PLACES)
    has_place = rng.random() < 0.7

    # thread: 상대 제안/질문 → 내 구체 제안 → (장소 공유) ; final: 상대 "네"
    t0 = f"{rng.choice([9,10,13,14]):02d}:{rng.choice([5,12,20,33]):02d}"
    opener = rng.choice([
        f"{act} 가능한 일정이 있으실까요?",
        f"{act} 언제가 편하세요?",
        f"이번에 {act} 한번 뵙고 싶습니다. 편한 시간 알려주세요.",
        f"제가 이번 주랑 다음 주에 시간이 됩니다. {act} 언제가 좋으세요?",
    ])
    my_propose = f"{surf_d} {ttext}" + (f" {place_disp}" if has_place else "") + rng.choice([
        " 가능합니다", "에 뵐게요", " 괜찮습니다", "로 하시죠", " 어떠세요?",
    ])
    thread = [
        {"time": t0, "sender": other, "message": opener},
        {"time": _plus(t0, 3), "sender": "나", "message": my_propose},
    ]
    if has_place and addr and rng.random() < 0.6:
        thread.append({"time": _plus(t0, 6), "sender": other, "message": "찾아갈 주소 알려 주세요."})
        thread.append({"time": _plus(t0, 8), "sender": "나", "message": f"[네이버지도] {addr}"})

    recv_dt = f"{recv.isoformat()}T{_plus(t0,10)}:00+09:00"
    ev = {
        "title": act, "date": tok_d,
        "time": {"hour": hh, "minute": mm, "marker": marker},
        "end_time": None, "all_day": False,
        "location": place_disp if has_place else None,
        "attendees": [], "organizer": None, "description": None,
        "recurrence": None, "confidence": round(rng.uniform(0.88, 0.95), 2),
    }
    return {
        "received_at": recv_dt, "channel": "kakao", "sender": other, "language": "ko",
        "thread_context": thread, "message": rng.choice(CONFIRMS),
        "gold": {"has_schedule": True, "events": [ev]},
        "_intended": intended.isoformat(),
    }


def make_neg(rng, recv: date) -> dict:
    """음성 2종:
      (a) 로지스틱스: '네'가 주소/자료 송부 등 비일정 요청에 대한 응답 (일정 단서 없음).
      (b) 거절/유보: 시각 단서가 '있는데도' 합의 안 됨 — '네=무조건 일정' 과학습 방지(핵심).
    """
    other = rng.choice(OTHERS)
    t0 = f"{rng.choice([9,10,14,16]):02d}:{rng.choice([3,18,27,40]):02d}"
    if rng.random() < 0.5:
        # (a) 로지스틱스 — '네'가 비일정 요청 응답. 최종은 그 항목을 가리키는 사례별 감사/응답(다양화).
        item, q, a = rng.choice([
            ("주소", "주소 좀 보내주실 수 있을까요?", "네 지금 보내드릴게요"),
            ("자료", "아까 그 자료 공유 부탁드려요.", "네 메일로 보내드렸습니다"),
            ("계좌번호", "계좌번호 알려주시겠어요?", "네 문자로 남겼습니다"),
            ("발표 파일", "발표 파일 한번 검토 부탁드립니다.", "네 확인하고 회신드릴게요"),
            ("명단", "명단 정리되면 알려주세요.", "네 정리되는 대로 공유할게요"),
            ("링크", "참가 링크 다시 보내주실 수 있나요?", "네 방금 다시 보냈습니다"),
            ("연락처", "담당자 연락처 좀 알려주세요.", "네 캡처해서 드릴게요"),
        ])
        thread = [
            {"time": t0, "sender": "나", "message": q},
            {"time": _plus(t0, 2), "sender": other, "message": a},
        ]
        final_sender = "나"
        final = rng.choice([f"{item} 잘 받았습니다 감사합니다", f"네 {item} 확인했습니다 감사해요",
                            f"{item} 감사합니다", "넵 감사합니다 잘 받았어요"])
    else:
        # (b) 거절/유보 — 시각 단서 '있는데도' 합의 없음(과트리거 방지 핵심). 메시지 다양화.
        act = rng.choice(ACTS_1on1)
        ttext = rng.choice(TIMES)[0]
        surf_d = rng.choice(["내일", "모레", "금요일", "다음 주 화요일", "이번 주 목요일", "다음 주 월요일"])
        thread = [
            {"time": t0, "sender": other, "message": f"{surf_d} {ttext} {act} 가능하세요?"},
        ]
        final_sender = "나"
        final = rng.choice([
            f"{surf_d}은 선약이 있어서 어려울 것 같아요",
            f"{surf_d} {ttext}은 곤란하고 다른 시간은 어떨까요?",
            f"{act}은 일정 확인하고 다시 연락드릴게요",
            f"{surf_d}은 힘들 것 같습니다. 조율 후 알려드릴게요",
            f"그 시간은 어려운데 {act} 다음 주로 미뤄도 될까요?",
            "음 조금 더 조율해봐야 할 것 같습니다",
        ])
    recv_dt = f"{recv.isoformat()}T{_plus(t0,4)}:00+09:00"
    return {
        "received_at": recv_dt, "channel": "kakao", "sender": final_sender, "language": "ko",
        "thread_context": thread, "message": final,
        "gold": {"has_schedule": False, "events": []},
    }


def _plus(hhmm: str, mins: int) -> str:
    h, m = map(int, hhmm.split(":"))
    tot = (h * 60 + m + mins) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=90)
    ap.add_argument("--neg-ratio", type=float, default=0.33)
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--out", default="data/processed/r23_hardcases.jsonl")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # 날짜 풀: 전 요일(주말 횡단 위해 금/토 가중)
    pool = []
    d = date(2026, 6, 1)
    while d <= date(2026, 12, 31):
        pool += [d] * (2 if d.weekday() in (4, 5) else 1)
        d += timedelta(days=1)

    recs, n_neg = [], 0
    for i in range(args.n):
        recv = rng.choice(pool)
        if rng.random() < args.neg_ratio:
            r = make_neg(rng, recv); n_neg += 1
        else:
            r = make_pos(rng, recv)
        r["scenario_id"] = f"r23_otherconfirm_{i:03d}"
        recs.append(r)

    # --- 라벨 검증: 양성의 date 토큰이 의도 날짜로 resolve 되는지 (resolver 미러) ---
    bad = []
    for r in recs:
        intended = r.pop("_intended", None)
        if not r["gold"]["has_schedule"]:
            continue
        tok = r["gold"]["events"][0]["date"]
        recv_d = date.fromisoformat(r["received_at"][:10])
        got = resolve_date(recv_d, tok)
        if got is None or got.isoformat() != intended:
            bad.append((r["scenario_id"], tok, str(got), intended))
    if bad:
        for b in bad[:10]:
            print("LABEL MISMATCH:", b)
        raise SystemExit(f"{len(bad)} label mismatches — 생성 로직 점검 필요")

    print(f"  생성 {len(recs)}건  (확정 {len(recs)-n_neg} / 비일정음성 {n_neg}, label errors: 0)")
    if args.apply:
        p = Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {args.out}")
    else:
        print("(미리보기 — --apply 로 기록)")
        for r in recs[:3]:
            print(json.dumps(r, ensure_ascii=False)[:240])


if __name__ == "__main__":
    main()
