"""r24 하드케이스 — '방해 날짜(거절 옵션)가 섞인 멀티턴 확정'.

배경(r23 배포 후 실기기 실패): 박상로 카톡은 협의가 어수선하다 —
  나: "29일까지 마감이라 30일은 안되네요. 12일 이번 금요일 가능합니다"
  나: "금요일 10시 경북대 복지관 할리스카페"
  상대: "네"
정답은 '이번 금요일'(=가까운 금요일)인데, r23 모델은 거절된 날짜(30일)·여러 후보 사이에서
합의값을 못 골라 date="다음주"(weekday 탈락 + 이번→다음 혼동)를 냈다(6/12→6/18 오인).

r23 생성기(gen_other_confirm)는 내 제안이 '깔끔한 단일 날짜'뿐이라 이 '방해 날짜' 구조가 없었다.
이 생성기가 그 갭을 메운다:
  - 상대가 두 날짜(합의+거절)를 제시하거나, 내가 한 날짜를 거절하고 다른 날짜로 확정.
  - 최종은 상대의 맨 "네", 일정 값은 내 메시지(요일+N일 병기, 박상로처럼).
  - gold = '합의' 날짜의 요일 토큰(이번주금 등). 관측된 '다음주' 편향 상쇄 위해 이번주 가중.
라벨은 _common.resolve_date로 검증(라벨오류 0, 유료 API 미사용).
출력: data/processed/r24_hardcases.jsonl   사용: python scripts/gen_distractor_confirm.py [--apply]
"""
from __future__ import annotations
import argparse, json, random, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import resolve_date

WD = ["월", "화", "수", "목", "금", "토", "일"]
TIMES = [
    ("오전 10시", 10, 0, "오전"), ("오전 11시", 11, 0, "오전"), ("낮 12시", 12, 0, "낮"),
    ("오후 2시", 2, 0, "오후"), ("오후 3시", 3, 0, "오후"), ("오후 4시", 4, 0, "오후"),
    ("저녁 6시", 6, 0, "저녁"), ("저녁 7시", 7, 0, "저녁"), ("10시", 10, 0, None), ("3시", 3, 0, None),
]
OTHERS = ["박상로", "김교수님", "이대표", "최팀장", "정선생님", "한과장", "윤원장님", "조실장님"]
ACTS = ["멘토링", "미팅", "면담", "상담", "점심", "저녁", "인터뷰", "자문"]
PLACES = [
    ("경북대 복지관 할리스카페", "할리스 쿱카페 경북대 크누라운지점 대구 북구 대학로 80 복지관"),
    ("강남역 스타벅스", None), ("판교역 1번 출구", None), ("코엑스 3층 카페", None),
    ("시청 앞 투썸", None), ("동성로 엔제리너스", None), ("회사 1층 로비", None),
]
CONFIRMS = ["네", "네 좋습니다", "네 그때 뵙겠습니다", "확인했습니다", "넵 알겠습니다",
            "네 그때 봬요", "좋습니다 그때 뵐게요", "예 알겠습니다 그때 뵙죠"]


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_token(recv: date, target_wd: int) -> tuple[str, date]:
    days_ahead = (target_wd - recv.weekday()) % 7
    upcoming = recv + timedelta(days=days_ahead)
    this_week = monday_of(recv) + timedelta(days=target_wd)
    prefix = "이번주" if upcoming == this_week else "다음주"
    return prefix + WD[target_wd], upcoming


def wd_surface(rng, token: str, wd_idx: int) -> str:
    """gold 토큰 → 메시지 표면형(요일). 이번주는 '이번 금요일'/'금요일', 다음주는 '다음 주 금요일'."""
    w = WD[wd_idx]
    if token.startswith("다음주"):
        return f"다음 주 {w}요일"
    return rng.choice([f"이번 {w}요일", f"{w}요일", f"이번 주 {w}요일"])


def _plus(hhmm: str, mins: int) -> str:
    h, m = map(int, hhmm.split(":"))
    tot = (h * 60 + m + mins) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def make_pos(rng, recv: date) -> dict:
    other = rng.choice(OTHERS)
    act = rng.choice(ACTS)
    # 이번주 70% 가중(관측된 '다음주' 편향 상쇄). 합의 요일은 월~금.
    agr_wd = rng.choice([0, 1, 2, 3, 4, 4])
    tok, agr_date = week_token(recv, agr_wd)
    if rng.random() < 0.70 and tok.startswith("다음주"):
        # 이번주로 당기기: 같은 요일이 이번 주에 아직 안 지났으면 이번주 사용
        tw = monday_of(recv) + timedelta(days=agr_wd)
        if tw >= recv:
            tok, agr_date = "이번주" + WD[agr_wd], tw
    agr_day = agr_date.day
    # 거절된 날짜(방해): 합의 이후 11~20일 뒤의 다른 날 (박상로의 '30일'처럼)
    rej_date = agr_date + timedelta(days=rng.choice([11, 13, 14, 17, 18, 20]))
    rej_day, rej_wd = rej_date.day, WD[rej_date.weekday()]
    surf = wd_surface(rng, tok, agr_wd)
    ttext, hh, mm, marker = rng.choice(TIMES)
    place_disp, addr = rng.choice(PLACES)
    has_place = rng.random() < 0.75

    t0 = f"{rng.choice([9,10,13,14]):02d}:{rng.choice([5,15,22,33]):02d}"
    # 상대가 두 날짜 제시(합의+거절) 또는 가능시간 문의
    opener = rng.choice([
        f"{agr_day}일({WD[agr_wd]})이나 {rej_day}일({rej_wd})에만 일정이 비어 있네요. 확인하시고 알려 주세요.",
        f"{act} 가능한 날이 {agr_day}일이나 {rej_day}일인데 편한 쪽 알려주세요.",
        f"이번에 {act} 뵙고 싶은데 편한 날 알려주세요.",
    ])
    # 나: 한쪽 거절 + 합의 날짜 확정(요일+N일 병기 — 박상로 패턴)
    narrow = rng.choice([
        f"{rej_day}일은 선약이 있어 어렵고 {agr_day}일 {surf} 가능합니다",
        f"{rej_day}일은 안 되고 {agr_day}일 {surf}로 하시죠",
        f"마감이 있어 {rej_day}일은 곤란하고 {agr_day}일 {surf}이 좋겠어요",
    ])
    propose = f"{surf} {ttext}" + (f" {place_disp}" if has_place else "") + rng.choice([" 가능합니다", "에 뵐게요", "로 뵙겠습니다"])
    thread = [
        {"time": t0, "sender": other, "message": opener},
        {"time": _plus(t0, 4), "sender": "나", "message": narrow},
    ]
    if has_place and addr and rng.random() < 0.5:
        thread.append({"time": _plus(t0, 7), "sender": other, "message": "찾아갈 주소 알려 주세요."})
        thread.append({"time": _plus(t0, 9), "sender": "나", "message": f"[네이버지도] {addr}"})
    thread.append({"time": _plus(t0, 11), "sender": "나", "message": propose})

    recv_dt = f"{recv.isoformat()}T{_plus(t0,13)}:00+09:00"
    ev = {"title": act, "date": tok, "time": {"hour": hh, "minute": mm, "marker": marker},
          "end_time": None, "all_day": False, "location": place_disp if has_place else None,
          "attendees": [], "organizer": None, "description": None, "recurrence": None,
          "confidence": round(rng.uniform(0.88, 0.95), 2)}
    return {"received_at": recv_dt, "channel": "kakao", "sender": other, "language": "ko",
            "thread_context": thread, "message": rng.choice(CONFIRMS),
            "gold": {"has_schedule": True, "events": [ev]}, "_intended": agr_date.isoformat()}


def make_neg(rng, recv: date) -> dict:
    """방해 날짜는 오갔으나 '합의 안 됨'(역제안/유보) → false. '날짜 여러 개 + 네 = 무조건 일정' 방지."""
    other = rng.choice(OTHERS); act = rng.choice(ACTS)
    a = rng.choice([8, 12, 15, 18, 22]); b = a + rng.choice([5, 7, 10])
    t0 = f"{rng.choice([9,10,14]):02d}:{rng.choice([10,25,40]):02d}"
    thread = [{"time": t0, "sender": other,
               "message": f"{a}일이나 {b}일에 {act} 가능하세요?"}]
    final = rng.choice([
        f"두 날 다 어려울 것 같아요. 다른 날 없을까요?",
        f"{a}일은 선약이고 {b}일도 애매해서 좀 더 보고 알려드릴게요",
        "일정 확인하고 다시 연락드리겠습니다",
        "그 주는 어렵고 다음 달로 미뤄도 될까요?",
    ])
    return {"received_at": f"{recv.isoformat()}T{_plus(t0,3)}:00+09:00", "channel": "kakao",
            "sender": "나", "language": "ko", "thread_context": thread, "message": final,
            "gold": {"has_schedule": False, "events": []}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=110)
    ap.add_argument("--neg-ratio", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--out", default="data/processed/r24_hardcases.jsonl")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    pool = []
    d = date(2026, 6, 1)
    while d <= date(2026, 12, 31):
        if d.weekday() <= 3:  # 월~목만 recv(이번주 금요일 등이 미래로 남게)
            pool.append(d)
        d += timedelta(days=1)

    recs, n_neg = [], 0
    for i in range(args.n):
        recv = rng.choice(pool)
        if rng.random() < args.neg_ratio:
            r = make_neg(rng, recv); n_neg += 1
        else:
            r = make_pos(rng, recv)
        r["scenario_id"] = f"r24_distractor_{i:03d}"
        recs.append(r)

    bad = []
    for r in recs:
        intended = r.pop("_intended", None)
        if not r["gold"]["has_schedule"]:
            continue
        tok = r["gold"]["events"][0]["date"]
        got = resolve_date(date.fromisoformat(r["received_at"][:10]), tok)
        if got is None or got.isoformat() != intended:
            bad.append((r["scenario_id"], tok, str(got), intended))
    if bad:
        for b in bad[:10]:
            print("LABEL MISMATCH:", b)
        raise SystemExit(f"{len(bad)} label mismatches")

    print(f"  생성 {len(recs)}건  (확정 {len(recs)-n_neg} / 음성 {n_neg}, label errors: 0)")
    if args.apply:
        p = Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {args.out}")
    else:
        print("(미리보기 — --apply 로 기록)")
        for r in recs[:3]:
            print(json.dumps(r, ensure_ascii=False)[:260])


if __name__ == "__main__":
    main()
