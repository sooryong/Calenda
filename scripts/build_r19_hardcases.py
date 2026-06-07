"""r19 하드케이스 빌더 — 제목 충실도 + 그룹채팅 일정 통합 (할루시네이션 제거).

진단(배포 r18 실추론): 활동명사 복사 능력은 있으나(동창회/회식/등산 ✓) "동기회 참석"→"기타 회의"로 창작.
informal 모임 어휘 희소 + "참석"→"회의" 연상 = 데이터 문제. 또 번호목록 누적 시 다중일정·설명 창작.
→ r19 데이터로 (1) 모임 제목 충실 (2) 번호목록 누적=단일 일정(참석자 union) 을 강하게 신호.

그룹:
  G1 informal 모임 title-faithful 양성 — gold title = 메시지 활동구 그대로(일반어 창작 금지).
  G2 번호목록 참석자 + 그룹 누적 멀티턴 — 각 메시지가 같은 title·date, attendees=목록 전체.
  G3 모임테마 하드네거티브 — 회비·지난모임·광고·유보 = has_schedule:false (과발화 방지).
  G4 무시간 모임 → time:null 종일.

출력: data/processed/r19_hardcases.jsonl
사용: python scripts/build_r19_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

RECV_BASE = "2026-06-07"  # received_at 기준일(상대토큰은 gold에 토큰으로 저장 → 절대일자 무관)


def ev(title, date, *, time=None, all_day=False, attendees=None, organizer=None,
       location=None, confidence=0.9):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": None, "recurrence": None, "confidence": confidence}


def T(h, m=0, marker=None):
    return {"hour": h, "minute": m, "marker": marker}


# ── G1: informal 모임 title-faithful 양성 (title = 활동구 그대로) ──────────────
# (channel, sender, message, event)
GATHER_POS = [
    ("kakao", "동기회총무", "다음주 금요일 저녁 7시 동기회", ev("동기회", "다음주금", time=T(7, marker="저녁"))),
    ("kakao", "강상욱", "6/16 동기회 참석", ev("동기회", "2026-06-16", all_day=True)),
    ("kakao", "김동창", "이번주 토요일 12시 동창회 모임", ev("동창회 모임", "이번주토", time=T(12))),
    ("kakao", "박팀장", "다음주 금요일 저녁 7시 팀 회식", ev("팀 회식", "다음주금", time=T(7, marker="저녁"))),
    ("kakao", "이부장", "이번주 일요일 아침 8시 북한산 등산", ev("북한산 등산", "이번주일", time=T(8, marker="아침"))),
    ("kakao", "조기축구회", "이번주 토요일 오전 10시 조기축구", ev("조기축구", "이번주토", time=T(10, marker="오전"))),
    ("kakao", "회장", "다음주 수요일 저녁 6시 송년회", ev("송년회", "다음주수", time=T(6, marker="저녁"))),
    ("kakao", "동기", "내일 저녁 6시 신년회", ev("신년회", "내일", time=T(6, marker="저녁"))),
    ("kakao", "팀장", "다음주 월요일 오전 10시 워크샵", ev("워크샵", "다음주월", time=T(10, marker="오전"))),
    ("kakao", "스터디장", "이번주 목요일 저녁 8시 스터디 모임", ev("스터디 모임", "이번주목", time=T(8, marker="저녁"))),
    ("kakao", "동아리", "다음주 토요일 MT 갑니다", ev("MT", "다음주토", all_day=True)),
    ("kakao", "친구", "이번주 토요일 점심 번개", ev("번개", "이번주토", time=T(12))),
    ("kakao", "이모", "다음주 일요일 집들이", ev("집들이", "다음주일", all_day=True)),
    ("kakao", "후배", "다음주 금요일 저녁 7시 환영회", ev("환영회", "다음주금", time=T(7, marker="저녁"))),
    ("kakao", "동료", "이번주 금요일 저녁 7시 송별회", ev("송별회", "이번주금", time=T(7, marker="저녁"))),
    ("kakao", "독서모임", "다음주 화요일 저녁 7시 독서모임", ev("독서모임", "다음주화", time=T(7, marker="저녁"))),
    ("kakao", "동창", "다음주 토요일 동창 모임", ev("동창 모임", "다음주토", all_day=True)),
    ("kakao", "부서", "다음주 수요일 12시 부서 회식", ev("부서 회식", "다음주수", time=T(12))),
    ("kakao", "가족방", "이번주 일요일 점심 가족 모임", ev("가족 모임", "이번주일", time=T(12))),
    ("kakao", "산악회", "다음주 일요일 아침 7시 산악회 정기산행", ev("산악회 정기산행", "다음주일", time=T(7, marker="아침"))),
    ("sms", "01122223333", "내일 저녁 6시 동기 모임", ev("동기 모임", "내일", time=T(6, marker="저녁"))),
    ("kakao", "모임장", "6/20 정기모임 참석", ev("정기모임", "2026-06-20", all_day=True)),
    ("kakao", "회장", "이번주 토요일 오후 6시 정모", ev("정모", "이번주토", time=T(6, marker="오후"))),
    ("kakao", "교회청년부", "이번주 토요일 오후 2시 봉사활동", ev("봉사활동", "이번주토", time=T(2, marker="오후"))),
]

# ── G4: 무시간 모임 → time:null 종일 (G1과 합쳐 학습) ──────────────────────────
GATHER_ALLDAY_POS = [
    ("kakao", "동기회", "다음주 토요일 동기회", ev("동기회", "다음주토", all_day=True)),
    ("kakao", "동창회", "6/22 동창회", ev("동창회", "2026-06-22", all_day=True)),
    ("kakao", "향우회", "다음주 일요일 향우회 모임", ev("향우회 모임", "다음주일", all_day=True)),
    ("kakao", "동기", "6/16 동기회 참석합니다", ev("동기회", "2026-06-16", all_day=True)),
]

# ── G3: 모임테마 하드네거티브 (has_schedule:false) ────────────────────────────
GATHER_NEG = [
    ("kakao", "동기회총무", "동기회 회비 입금 안내드립니다. 국민은행 123-45-678901 5만원"),
    ("kakao", "동창회", "지난 토요일 동창회 사진 공유합니다~ 다들 즐거우셨죠?"),
    ("kakao", "모임장", "다음 모임 날짜는 추후 다시 공지하겠습니다"),
    ("kakao", "이벤트", "[광고] 송년회 장소 예약 이벤트! 지금 예약하면 10% 할인"),
    ("kakao", "회장", "동기회 회칙 개정안 파일 첨부합니다. 검토 부탁드려요"),
    ("kakao", "동호회", "회식 장소 추천 좀 받을게요~ 어디가 좋을까요?"),
    ("kakao", "친구", "다들 등산 좋아해? 언제 한번 가자ㅋㅋ"),
    ("sms", "0212345678", "[국민] 동기회비 50,000원 입금되었습니다"),
    ("kakao", "총무", "송년회 회비 미납자 명단입니다\n1. 김철수\n2. 이영희\n3. 박민수"),
    ("kakao", "모임", "오늘 번개 취소합니다. 다음에 봐요"),
    ("kakao", "동아리", "MT 참가 신청은 구글폼으로 받습니다 (링크 참고)"),
    ("kakao", "운영진", "정기모임 회비 인상 관련 투표 진행 중입니다"),
]


def pos_rows(records, prefix):
    out = []
    for i, (ch, sender, msg, e) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{8 + (i % 12):02d}:{(i * 7) % 60:02d}:00+09:00",
                    "channel": ch, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": True, "events": [e]}})
    return out


def neg_rows(records, prefix):
    out = []
    for i, (ch, sender, msg) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{9 + (i % 12):02d}:{(i * 13) % 60:02d}:00+09:00",
                    "channel": ch, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": False, "events": []}})
    return out


def thread_rows(prefix, title, date, names, room_msgs, *, all_day=True, time=None):
    """번호목록 누적 멀티턴. names를 점진적으로 추가하며 각 단계 row 생성.
    각 row: 현재 메시지=활동구+번호목록(현재까지), thread_context=직전 메시지들,
            gold=같은 title·date, attendees=현재까지 전체."""
    out = []
    base_line = room_msgs["base_line"]            # 예: "6/16 동기회 참석"
    senders = room_msgs["senders"]                # 각 단계 발신자
    history = []                                   # thread_context 누적
    for step in range(len(names)):
        roster = names[: step + 1]
        listed = "\n".join(f"{j+1}. {n}" for j, n in enumerate(roster))
        msg = f"{base_line}\n{listed}"
        sender = senders[step]
        # 첫 1~2단계는 양성 row로 만들기엔 화자가 적어도 활동구가 있으므로 유효. 전부 생성.
        row = {"scenario_id": f"{prefix}_{step:02d}",
               "received_at": f"{RECV_BASE}T{13 + step:02d}:{(step * 9) % 60:02d}:00+09:00",
               "channel": "kakao", "sender": sender, "language": "ko",
               "message": msg,
               "gold": {"has_schedule": True, "events": [
                   ev(title, date, all_day=all_day, time=time, attendees=list(roster), confidence=0.95)]}}
        if history:
            row["thread_context"] = [dict(h) for h in history[-3:]]
        out.append(row)
        history.append({"time": f"{13 + step:02d}:{(step * 9) % 60:02d}", "sender": sender, "message": msg})
    return out


def build_threads():
    rows = []
    # T1 — 동기회 6/16 (실제 실패 케이스 미러)
    rows += thread_rows("g19_thr_donggi", "동기회", "2026-06-16",
                        ["강상욱", "홍미정", "정순원", "여상재"],
                        {"base_line": "6/16 동기회 참석",
                         "senders": ["강상욱", "홍미정", "정순원", "여상재"]})
    # T2 — 워크샵 다음주 목요일
    rows += thread_rows("g19_thr_works", "워크샵", "다음주목",
                        ["김민수", "이지은", "박서준"],
                        {"base_line": "다음주 목요일 워크샵 참석자",
                         "senders": ["김민수", "이지은", "박서준"]})
    # T3 — 등산모임 이번주 일요일
    rows += thread_rows("g19_thr_hike", "등산", "이번주일",
                        ["최우식", "한소희", "류준열"],
                        {"base_line": "이번주 일요일 등산 가실 분",
                         "senders": ["최우식", "한소희", "류준열"]})
    # T4 — 회식 다음주 금요일 저녁 7시 (시간 있는 누적)
    rows += thread_rows("g19_thr_hoesik", "팀 회식", "다음주금",
                        ["정대리", "김과장", "이사원"],
                        {"base_line": "다음주 금요일 저녁 7시 팀 회식 참석자",
                         "senders": ["정대리", "김과장", "이사원"]},
                        all_day=False, time=T(7, marker="저녁"))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    groups = {
        "G1 모임 충실 양성": pos_rows(GATHER_POS, "g19_gather"),
        "G4 무시간 종일": pos_rows(GATHER_ALLDAY_POS, "g19_allday"),
        "G2 번호목록 누적 멀티턴": build_threads(),
        "G3 모임테마 음성": neg_rows(GATHER_NEG, "g19_gneg"),
    }
    rows = [r for g in groups.values() for r in g]
    pos = sum(1 for r in rows if r["gold"]["has_schedule"])
    neg = len(rows) - pos
    for name, g in groups.items():
        gp = sum(1 for r in g if r["gold"]["has_schedule"])
        print(f"  {name:24} {len(g):3}  (양성 {gp}, 음성 {len(g)-gp})")
    print(f"  {'합계':24} {len(rows):3}  (양성 {pos} / 음성 {neg}, 음성 {neg/len(rows):.0%})")
    if args.apply:
        p = "data/processed/r19_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
