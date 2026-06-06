"""r18 하드케이스 빌더 — "r16 + N일 종일 픽스" (회귀 없이 공백만 닫기).

배경: r17은 단독 N일 양성으로 "11일 실업급여" 검출엔 성공했으나(공백 닫힘),
r17 round 전체는 r16 대비 회귀(precision↓·loc↓; 합성 음성 과트리거 + 2000캡 자기참조 잠식).
→ r18은 **r16 데이터(base_r16.jsonl, git 복원 0.827)를 안정 pool로** 두고,
   r17의 과트리거 음성은 빼고 **N일 종일 양성만** 더한다.

핵심 타깃: 단독 'N일'(월 없음) + **시간 없음 = 종일**(time=null, all_day=true).
  r17에서 모델이 "11일"의 숫자 11을 시각 11시로 환각 → time:null을 다양한 일자로 강하게 신호.
  (오늘 이후면 이번달, 아니면 다음달은 resolver가 처리. 과거는 의도 아님 = 라벨도 미래.)

출력: data/processed/r18_hardcases.jsonl
사용: python scripts/build_r18_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

BASE_DAYS = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-15", "2026-06-16", "2026-06-17"]


def ev(title, date, *, time=None, all_day=False, organizer=None, confidence=0.86):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": None, "attendees": [], "organizer": organizer,
            "description": None, "recurrence": None, "confidence": confidence}


# 단독 N일 + 시간없음 종일 (time=null!). 일자를 1~31 다양하게(특히 1~12 = 시각 혼동 위험대).
ADMIN_NDAY_POS = [
    ("sms", "01038139885", "11일 실업급여 인터넷신청", ev("실업급여 인터넷신청", "11일", all_day=True, confidence=0.88)),
    ("sms", "국세청", "10일 종합소득세 신고", ev("종합소득세 신고", "10일", all_day=True, confidence=0.88)),
    ("sms", "위택스", "9일 자동차세 납부", ev("자동차세 납부", "9일", all_day=True, confidence=0.88)),
    ("kakao", "총무팀", "12일 사업자 서류 제출", ev("사업자 서류 제출", "12일", all_day=True, confidence=0.86)),
    ("sms", "관리사무소", "28일 관리비 납부", ev("관리비 납부", "28일", all_day=True, confidence=0.86)),
    ("sms", "01044448888", "8일 건강검진", ev("건강검진", "8일", all_day=True, confidence=0.85)),
    ("sms", "외교부", "25일 여권 재발급 신청", ev("여권 재발급 신청", "25일", all_day=True, confidence=0.86)),
    ("gmail", "bursar@univ.ac.kr", "7일 등록금 납부", ev("등록금 납부", "7일", all_day=True, confidence=0.86)),
    ("sms", "홈택스", "2일 부가세 신고", ev("부가세 신고", "2일", all_day=True, confidence=0.88)),
    ("sms", "장학재단", "12일 국가장학금 신청 마감", ev("국가장학금 신청 마감", "12일", all_day=True, confidence=0.88)),
    ("kakao", "박대리", "5일 정기점검 방문", ev("정기점검 방문", "5일", all_day=True, confidence=0.84)),
    ("gmail", "hr@bigco.com", "18일 계약서 제출", ev("계약서 제출", "18일", all_day=True, confidence=0.86)),
    ("sms", "01055556666", "3일 차량 정기검사", ev("차량 정기검사", "3일", all_day=True, confidence=0.85)),
    ("sms", "도서관", "15일 대출도서 반납", ev("대출도서 반납", "15일", all_day=True, confidence=0.85)),
    ("kakao", "동창회", "21일 동창 모임", ev("동창 모임", "21일", all_day=True, confidence=0.84)),
    ("sms", "01099998888", "6일 이사", ev("이사", "6일", all_day=True, confidence=0.84)),
]

# 단독 N일 + 시간 있음 (date='N일' 토큰 유지, time은 별개로 명시될 때만)
NDAY_TIME_POS = [
    ("sms", "01038139885", "11일 오후 2시 실업급여 상담", ev("실업급여 상담", "11일", time={"hour": 2, "minute": 0, "marker": "오후"}, confidence=0.86)),
    ("sms", "1577", "22일 오전 10시 치과 예약", ev("치과 예약", "22일", time={"hour": 10, "minute": 0, "marker": "오전"}, confidence=0.85)),
    ("kakao", "이팀장", "8일 오후 4시 거래처 미팅", ev("거래처 미팅", "8일", time={"hour": 4, "minute": 0, "marker": "오후"}, confidence=0.85)),
]

# 'N일까지' 마감형
NDAY_DEADLINE_POS = [
    ("gmail", "apply@nipa.kr", "21일까지 지원사업 서류 접수", ev("지원사업 서류 접수 마감", "21일", all_day=True, confidence=0.86)),
    ("sms", "정부24", "10일까지 보조금 신청", ev("보조금 신청 마감", "10일", all_day=True, confidence=0.86)),
]


def pos_rows(records, prefix):
    out = []
    for i, (ch, sender, msg, e) in enumerate(records):
        day = BASE_DAYS[i % len(BASE_DAYS)]; hour = 8 + (i % 12)
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{day}T{hour:02d}:{(i*11)%60:02d}:00+09:00",
                    "channel": ch, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": True, "events": [e]}})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    groups = {
        "N일 종일(time=null)": pos_rows(ADMIN_NDAY_POS, "g18_ndayallday"),
        "N일+시간": pos_rows(NDAY_TIME_POS, "g18_ndaytime"),
        "N일까지 마감": pos_rows(NDAY_DEADLINE_POS, "g18_ndaydl"),
    }
    rows = [r for g in groups.values() for r in g]
    for name, g in groups.items():
        print(f"  {name:18} {len(g):3}")
    print(f"  {'합계':18} {len(rows):3}  (전부 양성)")
    if args.apply:
        p = "data/processed/r18_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
