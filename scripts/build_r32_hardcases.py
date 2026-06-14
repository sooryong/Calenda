"""r32 하드케이스 — '조직팀 + 온라인도구' 자연제목 패턴 소량 보강.

배경: 전체 Haiku 재라벨로 자연제목 규칙은 bulk가 담당. 그러나 실사용 실패 구조
("AWS 교육팀과 줌회의" = 조직팀 참석자 + 도구 woven)가 재라벨 후에도 2건뿐(희소).
→ 이 표면형만 ~25 보강. gold title=메시지에서 시간만 제외한 자연제목, location=도구/venue.

원칙: 직접 생성, 깨끗한 SMS/카톡 문장(잡담 없음 → title=message-시간). 골든과 표면형 분리.
출력: data/processed/_r32_add.jsonl
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

def ev(title, date, time, location, conf=0.93):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": False,
            "location": location, "attendees": [], "organizer": None, "description": None,
            "recurrence": None, "confidence": conf}

def row(sid, recv, ch, sender, msg, events):
    return {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
            "language": "ko", "message": msg, "gold": {"has_schedule": True, "events": events}}

# (제목, date, time, location, 채널, 발신자)  — 메시지는 "{dword} {tword} {제목}" 으로 합성(self/clean)
T = lambda h, m, mk: {"hour": h, "minute": m, "marker": mk}
DW = {"내일":"내일","모레":"모레","다음주월":"다음주 월요일","다음주화":"다음주 화요일","다음주수":"다음주 수요일",
      "다음주목":"다음주 목요일","다음주금":"다음주 금요일","이번주목":"이번주 목요일","이번주금":"이번주 금요일"}

CASES = [
    # 조직팀 + 도구 + 회의 (핵심 실패 구조)
    ("AWS 교육팀과 줌회의",        "내일",   T(1,0,"오후"), "줌",   "sms",  "나"),
    ("마케팅팀과 구글밋 회의",      "내일",   T(3,0,"오후"), "구글밋","kakao","박과장"),
    ("개발팀과 팀즈 점검",         "모레",   T(10,0,"오전"),"팀즈", "sms",  "나"),
    ("법무팀과 화상 미팅",         "다음주화", T(2,0,"오후"), "화상", "kakao","김부장"),
    ("디자인팀과 줌 리뷰",         "내일",   T(5,0,"오후"), "줌",   "sms",  "나"),
    ("영업팀과 웹엑스 미팅",        "다음주수", T(11,0,"오전"),"웹엑스","kakao","최팀장"),
    ("HR팀과 줌 면접",            "모레",   T(2,0,"오후"), "줌",   "gmail","hr@company.com"),
    ("재무팀과 팀즈 결산회의",      "다음주목", T(4,0,"오후"), "팀즈", "kakao","이대리"),
    ("기획팀과 구글밋 브리핑",      "내일",   T(9,30,"오전"),"구글밋","sms",  "나"),
    ("운영팀과 전화 점검회의",      "이번주금", T(3,0,"오후"), "전화", "kakao","정과장"),
    # X관련 온라인/화상 회의
    ("AWS 교육관련 온라인 회의",    "내일",   T(1,0,"오후"), "온라인","sms",  "나"),
    ("신제품 관련 화상 미팅",       "모레",   T(2,0,"오후"), "화상", "kakao","한부장"),
    ("예산 관련 줌 회의",          "다음주화", T(10,0,"오전"),"줌",   "gmail","cfo@company.com"),
    ("채용 관련 구글밋 미팅",       "내일",   T(4,0,"오후"), "구글밋","kakao","서팀장"),
    ("프로젝트 관련 팀즈 회의",     "다음주금", T(11,0,"오전"),"팀즈", "sms",  "나"),
    # 조직팀 + 물리 venue (woven)
    ("영업팀과 강남 사무실 미팅",    "내일",   T(2,0,"오후"), "강남 사무실","kakao","조부장"),
    ("교육팀과 본사 5층 워크숍",    "다음주수", T(9,0,"오전"), "본사 5층","gmail","edu@company.com"),
    ("동기회 멤버들과 역삼 스타벅스 모임","모레", T(7,0,"저녁"),"역삼 스타벅스","kakao","동기회방"),
    # 도구 woven, 짧은 형 (으로 없이)
    ("줌회의",                   "내일",   T(3,0,"오후"), "줌",   "sms",  "나"),
    ("구글밋 회의",               "모레",   T(10,0,"오전"),"구글밋","sms",  "나"),
    ("팀즈 점검",                "다음주목", T(2,0,"오후"), "팀즈", "kakao","유대리"),
    # 장소: 라벨형 (제목엔 제외 — 위치 필드만)  ※ 메시지에 라벨로 분리
    ("분기 실적보고",             "다음주화", T(2,0,"오후"), "본사 대회의실", "gmail","ceo@company.com"),
    ("전사 타운홀",              "다음주금", T(4,0,"오후"), "온라인", "gmail","hr@company.com"),
]

rows = []
for i, (title, d, t, loc, ch, snd) in enumerate(CASES):
    tword = (f"{t['marker']} " if t['marker'] else "") + f"{t['hour']}시" + (f" {t['minute']}분" if t['minute'] else "")
    dword = DW[d]
    if title in ("분기 실적보고", "전사 타운홀"):     # 장소: 라벨형 — 제목에 장소 없음
        msg = f"{dword} {tword} {title} 진행합니다.\n장소: {loc}"
    else:
        msg = f"{dword} {tword} {title}"            # clean self/안내 — title=message-시간
    rows.append(row(f"r32_team_{i:02d}", "2026-06-14T09:00:00+09:00", ch, snd, msg, [ev(title, d, t, loc)]))

# 검증
bad = 0
for r in rows:
    for e in r["gold"]["events"]:
        if e["date"] and resolve_when(r["received_at"], e["date"], e["time"], e["end_time"], e["all_day"])["start"] is None:
            bad += 1; print("  ! resolve 실패:", r["scenario_id"], e["date"])
print(f"생성 {len(rows)}행 (전부 양성) | resolve 실패 {bad}")
Path("data/processed/_r32_add.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print("→ data/processed/_r32_add.jsonl")
