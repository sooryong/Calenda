"""r33 하드케이스 — 환각 억제(시각·장소·설명) 양성.

배경(r32 실사용): 제목 자연보존은 성공했으나 모델이 보조 필드를 환각.
  A. 무시간 맥락에 **시각을 지어냄**(대구TP 간담회에 14:00) — 시각이 최우선 KPI라 가장 심각.
  B. 장소 미언급인데 **제목을 location에 복제**하거나 장소를 지어냄.
  C. 근거 없는 **description 환각**("이후 사진을 보냅니다", 인사말 흡수).

→ 세 카테고리의 깨끗한 양성으로 "없으면 null" 규율을 학습:
  A. 날짜는 있되 시각이 없는 일정 → time:null (종일 또는 시각미상). 절대 시각 부착 금지.
  B. 제목·시각은 분명하되 장소 미언급 → location:null. 제목을 location에 복제 금지.
  C. 본문에 부가정보 없음 + 인사말/잡담 trailing → description:null.

원칙: 직접 생성, 깨끗한 SMS/카톡/메일 문장. 골든과 표면형 분리. (= prompts/schema.md)
출력: data/processed/_r33_add.jsonl
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

T = lambda h, m, mk: {"hour": h, "minute": m, "marker": mk}


def ev(title, date, time, location=None, attendees=None, all_day=False, desc=None, conf=0.9):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": None,
            "description": desc, "recurrence": None, "confidence": conf}


def row(sid, recv, ch, sender, msg, events):
    return {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
            "language": "ko", "message": msg, "gold": {"has_schedule": True, "events": events}}


RECV = "2026-06-15T09:00:00+09:00"  # 월

# ───────────────────────────────────────────────────────────────────────────
# A. 무시간 → time:null  (★ 시각 환각 억제 — KPI 직결)
#    메시지에 시계 시각이 전혀 없음. 날짜만. 모델은 time:null 을 내야 함.
#    all_day=True: 종일성 행사 / all_day=False+time:null: 시각 미상 약속.
# ───────────────────────────────────────────────────────────────────────────
CASES_A = [
    # (제목, date, all_day, 채널, 발신자, 메시지)  ← 메시지에 시각 없음
    ("대구테크노파크 간담회", "내일", True,  "sms",  "나",     "내일 대구테크노파크 간담회 참석"),
    ("창립기념 행사",         "모레", True,  "gmail","hr@company.com", "모레 창립기념 행사가 있습니다. 많은 참석 바랍니다."),
    ("전사 워크숍",           "다음주월", True, "gmail","ceo@company.com", "다음주 월요일 전사 워크숍 진행 예정입니다."),
    ("팀 등산",              "토요일", True,  "kakao","박과장", "토요일에 팀 등산 가기로 했어요."),
    ("동기회 모임",          "다음주토", True, "kakao","동기회방", "다음주 토요일 동기회 모임 합니다~"),
    ("지역 축제",            "이번주말", True, "kakao","민지",   "이번 주말에 지역 축제 같이 갈래?"),
    ("프로젝트 마감",         "금요일", True,  "sms",  "나",     "금요일 프로젝트 마감"),
    ("정기 점검",            "수요일", True,  "sms",  "관리사무소", "수요일 정기 점검 예정입니다. 양해 부탁드립니다."),
    ("연수원 교육",          "다음주화", True, "gmail","edu@company.com", "다음주 화요일 연수원 교육이 잡혔습니다."),
    ("체육대회",             "다음주금", True, "kakao","총무",   "다음주 금요일 체육대회 진행합니다!"),
    # 시각 미상 약속 (all_day=False, time:null)
    ("김부장 면담",          "내일",  False, "sms",  "나",     "내일 김부장님이랑 면담하기로 했음"),
    ("치과 예약",            "모레",  False, "sms",  "나",     "모레 치과 예약 있음"),
    ("거래처 미팅",          "목요일", False, "kakao","최팀장", "목요일에 거래처 미팅 잡혔어요. 시간은 추후 공지할게요."),
    ("부모님 댁 방문",        "이번주말", False, "kakao","누나", "이번 주말에 부모님 댁 같이 가자."),
    ("계약서 검토 회의",      "다음주수", False, "gmail","legal@company.com", "다음주 수요일 계약서 검토 회의 예정입니다. 시간은 확정되면 안내드립니다."),
    ("스터디 모임",          "내일",  False, "kakao","지훈",   "내일 스터디 모임 하기로 한 거 잊지마"),
    # 막연한 맥락이지만 약속은 성립 (시각만 없음)
    ("저녁 식사",            "내일",  False, "kakao","민수",   "내일 일 끝나고 저녁이나 같이 먹자"),
    ("커피 한잔",            "모레",  False, "kakao","서연",   "모레 시간 되면 커피 한잔 하자~"),
]

# ───────────────────────────────────────────────────────────────────────────
# B. 무장소 → location:null  (★ 제목→location 복제 억제)
#    시각은 분명, 장소만 미언급. location:null 이어야 함.
# ───────────────────────────────────────────────────────────────────────────
CASES_B = [
    # (제목, date, time, 채널, 발신자, 메시지)
    ("대구TP 간담회",        "내일",   T(3,0,"오후"), "sms",  "나",     "내일 오후 3시 대구TP 간담회 참석"),
    ("신제품 출시 간담회",    "다음주월", T(2,0,"오후"), "gmail","pr@company.com", "다음주 월요일 오후 2시 신제품 출시 간담회 진행합니다."),
    ("분기 사업보고",        "모레",   T(10,0,"오전"),"gmail","ceo@company.com", "모레 오전 10시 분기 사업보고 있습니다."),
    ("주간 업무회의",        "내일",   T(9,30,"오전"),"kakao","박과장", "내일 오전 9시 반 주간 업무회의 합시다."),
    ("고객사 컨퍼런스콜",     "목요일", T(4,0,"오후"), "kakao","김대리", "목요일 오후 4시 고객사 컨퍼런스콜 있어요."),
    ("채용 면접",            "다음주화", T(11,0,"오전"),"gmail","hr@company.com", "다음주 화요일 오전 11시 채용 면접 예정입니다."),
    ("예산 심의",            "금요일", T(2,30,"오후"), "gmail","finance@company.com", "금요일 오후 2시 반 예산 심의가 있습니다."),
    ("정기 진료",            "다음주수", T(10,0,"오전"),"sms",  "나",     "다음주 수요일 오전 10시 정기 진료"),
    ("학부모 상담",          "내일",   T(5,0,"오후"), "sms",  "담임선생님", "내일 오후 5시 학부모 상담 진행하겠습니다."),
    ("디자인 시안 리뷰",      "모레",   T(3,0,"오후"), "kakao","유대리", "모레 오후 3시 디자인 시안 리뷰 하시죠."),
    ("계약 체결식",          "다음주목", T(1,0,"오후"), "gmail","biz@company.com", "다음주 목요일 오후 1시 계약 체결식 진행합니다."),
    ("월간 결산회의",        "수요일", T(4,0,"오후"), "kakao","이대리", "수요일 오후 4시 월간 결산회의 합니다."),
]

# ───────────────────────────────────────────────────────────────────────────
# C. 무근거 → description:null  (★ 설명 환각·인사말 흡수 억제)
#    날짜·시각·제목 분명. 본문 뒤 인사말/잡담은 description 으로 흡수하지 않음.
# ───────────────────────────────────────────────────────────────────────────
CASES_C = [
    # (제목, date, time, location, 채널, 발신자, 메시지)  ← trailing 잡담은 description 아님
    ("팀 회의",   "내일",   T(2,0,"오후"), None,        "kakao","박과장", "내일 오후 2시 팀 회의 합시다. 점심 맛있게 드세요~"),
    ("저녁 약속", "모레",   T(7,0,"저녁"), "강남역",     "kakao","민지",   "모레 저녁 7시 강남역에서 봐요. 그럼 이따 연락할게요 ㅎㅎ"),
    ("주간 보고", "수요일", T(10,0,"오전"),None,        "kakao","최팀장", "수요일 오전 10시 주간 보고 진행합니다. 다들 화이팅!"),
    ("점심 미팅", "내일",   T(12,0,"정오"),"회사 앞 식당","sms", "나",      "내일 정오 회사 앞 식당에서 점심 미팅. 배고프다 ㅋㅋ"),
    ("운동 모임", "금요일", T(7,0,"저녁"), "헬스장",     "kakao","준호",   "금요일 저녁 7시 헬스장 운동 모임. 사진은 나중에 보낼게"),
    ("프로젝트 리뷰","다음주화",T(3,0,"오후"),"줌",       "gmail","pm@company.com", "다음주 화요일 오후 3시 프로젝트 리뷰입니다. 좋은 하루 되세요."),
    ("동창 모임", "이번주토", T(6,0,"저녁"), "홍대",      "kakao","동창회방","이번 주 토요일 저녁 6시 홍대에서 동창 모임! 다들 꼭 와라ㅋㅋㅋ"),
    ("부서 회식", "목요일", T(6,30,"저녁"),"본사 근처 고깃집","kakao","팀장", "목요일 저녁 6시 반 본사 근처 고깃집에서 부서 회식합니다. 컨디션들 챙기세요~"),
]

rows = []
for i, (title, d, allday, ch, snd, msg) in enumerate(CASES_A):
    rows.append(row(f"r33_notime_{i:02d}", RECV, ch, snd, msg,
                    [ev(title, d, None, all_day=allday, conf=0.78 if not allday else 0.8)]))
for i, (title, d, t, ch, snd, msg) in enumerate(CASES_B):
    rows.append(row(f"r33_noloc_{i:02d}", RECV, ch, snd, msg,
                    [ev(title, d, t, location=None)]))
for i, (title, d, t, loc, ch, snd, msg) in enumerate(CASES_C):
    rows.append(row(f"r33_nodesc_{i:02d}", RECV, ch, snd, msg,
                    [ev(title, d, t, location=loc, desc=None)]))

# 검증: resolve round-trip + 필드 규율
bad = 0
for r in rows:
    for e in r["gold"]["events"]:
        res = resolve_when(r["received_at"], e["date"], e["time"], e["end_time"], e["all_day"])
        if e["date"] and res["start"] is None:
            bad += 1
            print("  ! resolve 실패:", r["scenario_id"], repr(e["date"]), e["time"], "all_day=", e["all_day"])

na = sum(1 for r in rows if r["scenario_id"].startswith("r33_notime"))
nb = sum(1 for r in rows if r["scenario_id"].startswith("r33_noloc"))
nc = sum(1 for r in rows if r["scenario_id"].startswith("r33_nodesc"))
print(f"생성 {len(rows)}행 (전부 양성): 무시간 {na} · 무장소 {nb} · 무설명 {nc} | resolve 실패 {bad}")
out = Path("data/processed/_r33_add.jsonl")
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"→ {out}")
