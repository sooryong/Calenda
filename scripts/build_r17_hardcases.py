"""r17 하드케이스 빌더 — r16 배포 후 발견된 공백 + 잔여 precision 약점.

(A) 단독 'N일' + 시간없음 + 행정업무 양성 [신규 핵심]:
    r16 로컬/온디바이스 테스트에서 "11일 실업급여 인터넷신청"이 has_schedule=false로 누락.
    원인: r16의 N일 양성은 전부 '시간 있음', date-only 양성은 '월 붙은 절대일자'였다 →
    "월 없는 단독 N일 + 시간 없음" 조합 미학습. (월·시 붙으면 정상 검출 확인됨.)
    → date 토큰 'N일'(resolver가 가까운 미래로), time=null, all_day=true, 명확하므로 confidence 높게(0.88).

(B) precision/과발화 [r16 specificity 0.571, 과발화 9] — 합성 효과 제한적이나 밀착 보강:
    광고(티샷·항공·쇼핑)·gmail업무(자료공유/회람/결과/리마인드)·재난·제3자. 실제 over-fire 패턴.

출력: data/processed/r17_hardcases.jsonl  (assemble_train.py가 'keep' 편입)
사용: python scripts/build_r17_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

NEG = {"has_schedule": False, "events": []}
BASE_DAYS = ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-15", "2026-06-16", "2026-06-17"]


def ev(title, date, *, time=None, all_day=False, location=None, attendees=None,
       organizer=None, confidence=0.85):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": None, "recurrence": None, "confidence": confidence}


# ── (A) 단독 N일 + 시간없음 + 행정업무 양성 (핵심 공백) ──────────────────────────────
# date='N일'(토큰), time=null, all_day=true. 행정 동사: 신청/제출/납부/신고/접수/마감/방문/예약.
ADMIN_NDAY_POS = [
    ("sms", "01038139885", "11일 실업급여 인터넷신청", ev("실업급여 인터넷신청", "11일", all_day=True, confidence=0.88)),
    ("sms", "국세청", "15일 종합소득세 신고", ev("종합소득세 신고", "15일", all_day=True, confidence=0.88)),
    ("sms", "위택스", "20일 자동차세 납부", ev("자동차세 납부", "20일", all_day=True, confidence=0.88)),
    ("kakao", "총무팀", "3일 사업자 서류 제출", ev("사업자 서류 제출", "3일", all_day=True, confidence=0.86)),
    ("sms", "관리사무소", "28일 관리비 납부", ev("관리비 납부", "28일", all_day=True, confidence=0.86)),
    ("sms", "01044448888", "9일 건강검진 예약", ev("건강검진 예약", "9일", all_day=True, confidence=0.86)),
    ("sms", "외교부", "25일 여권 재발급 신청", ev("여권 재발급 신청", "25일", all_day=True, confidence=0.86)),
    ("gmail", "bursar@univ.ac.kr", "7일 등록금 납부", ev("등록금 납부", "7일", all_day=True, confidence=0.86)),
    ("sms", "홈택스", "30일 부가세 신고", ev("부가세 신고", "30일", all_day=True, confidence=0.88)),
    ("sms", "장학재단", "12일 국가장학금 신청 마감", ev("국가장학금 신청 마감", "12일", all_day=True, confidence=0.88)),
    ("kakao", "박대리", "5일 정기점검 방문", ev("정기점검 방문", "5일", all_day=True, confidence=0.84)),
    ("gmail", "hr@bigco.com", "18일 계약서 제출", ev("계약서 제출", "18일", all_day=True, confidence=0.86)),
]

# (A2) 단독 N일 + 시간 있음 (보강 — date 토큰 'N일' 유지)
NDAY_TIME_POS = [
    ("sms", "01038139885", "11일 오후 2시 실업급여 상담", ev("실업급여 상담", "11일", time={"hour": 2, "minute": 0, "marker": "오후"}, confidence=0.86)),
    ("sms", "1577", "22일 10시 치과 예약", ev("치과 예약", "22일", time={"hour": 10, "minute": 0, "marker": "오전"}, confidence=0.85)),
    ("kakao", "이팀장", "8일 오후 4시 거래처 미팅", ev("거래처 미팅", "8일", time={"hour": 4, "minute": 0, "marker": "오후"}, attendees=["이팀장"], confidence=0.85)),
    ("sms", "01099998888", "17일 저녁 7시 동창 모임", ev("동창 모임", "17일", time={"hour": 7, "minute": 0, "marker": "저녁"}, confidence=0.84)),
]

# (A3) 'N일까지' 마감형 (단독 일자 + 마감)
NDAY_DEADLINE_POS = [
    ("gmail", "apply@nipa.kr", "21일까지 지원사업 서류 접수", ev("지원사업 서류 접수 마감", "21일", all_day=True, confidence=0.86)),
    ("sms", "정부24", "10일까지 보조금 신청", ev("보조금 신청 마감", "10일", all_day=True, confidence=0.86)),
    ("gmail", "edu@kocca.kr", "27일까지 교육 수료 과제 제출", ev("교육 수료 과제 제출 마감", "27일", all_day=True, confidence=0.85)),
]

# ── (B) precision 음성 ─────────────────────────────────────────────────────────
AD_NEG = [
    ("티샷", "[티샷] 회원님에게 골프조인 요청서가 도착했습니다.\n▶ 파인비치 ▶ 6.28(일) 7:12 ▶ 요청회원 이글퀸\n☞ 요청서를 확인해 보세요. 알림 신청에 의해 발송."),
    ("XGOLF", "[엑스골프] 마감임박! 6/25(수) 부킹 남은자리. 카트비 무료. 무료수신거부"),
    ("대한항공", "[대한항공] 보너스 항공권 특가 ~6월 24일(수) 오후 5시! 마일리지로 떠나세요. 수신거부"),
    ("아고다", "[아고다] 여름 호텔 6/22(월) 자정까지 최대 65% 할인코드. 지금 예약. 채널 차단"),
    ("11번가", "[11번가] 십일절 D-1! 6/11 단 하루 최대 90% 쿠폰. 광고 수신거부"),
    ("마켓컬리", "[컬리] 새벽배송 첫 주문 5천원 쿠폰! 오늘 밤 11시까지. 수신거부"),
    ("현대해상 김설계사", "사장님 좋은 아침입니다^^ 늘 건강하세요! 자동차보험 만기 다가옵니다. 갱신 상담 원하시면 편히 연락 주세요. 사은품 챙겨드려요!"),
    ("신한카드", "(광고) 6월 신규 발급 시 15만원 캐시백 ~6/30까지! 무료수신거부 080"),
]
GMAIL_BIZ_NEG = [
    ("admin@kised.or.kr", "[창업진흥원] 지난 데모데이 발표자료 및 사진 공유 — 참석해 주셔서 감사합니다."),
    ("edu@koef.or.kr", "[KoEF] 인스트럭터 워크북 v2 회람 — 검토 후 의견 회신 부탁드립니다."),
    ("hr@company.co.kr", "[인사] 1차 면접 결과 안내 — 합격자께는 개별 연락드립니다. 지원 감사합니다."),
    ("noreply@nps.or.kr", "[국민연금] 6월 납부내역서가 발급되었습니다. 마이페이지에서 확인하세요."),
    ("pm@office.kr", "[리마인드] 분기 보고서 양식 배포 — 작성해 회신 부탁드립니다. 마감 일정은 추후 공지."),
    ("secretary@assoc.or.kr", "이사회 회의록(초안) 회람 — 수정의견 있으시면 회신 바랍니다."),
]
DISASTER_NEG = [
    ("#CMAS#Severe", "[기상청] 오늘 17시 대설주의보. 빙판길·교통 혼잡 주의하세요."),
    ("안전안내문자", "[OO구] 단수 안내: 6/12 02~06시 노후관 교체로 단수 예정. 양해 바랍니다."),
    ("#CMAS#Emergency", "[행안부] 오늘 04:50 전남 신안 규모 3.8 지진. 여진 주의 바랍니다."),
    ("안전안내문자", "[질병청] 인플루엔자 유행주의보. 손씻기·기침예절 실천 바랍니다."),
]
THIRD_PARTY_NEG = [
    ("운영진방", "@정강사 6/26(금) 14시 워크숍 진행하셔야 합니다. 자료 전날까지 부탁해요."),
    ("프로젝트방", "민수가 6/24(화) 10시 클라이언트 발표 들어간대요. 우린 대기만 하면 됩니다."),
    ("팀채널", "수빈님 6/23(월) 연차라 그날 배포는 다른 분이 맡아주셔야 해요."),
    ("학부모방", "담임샘이 6/19(금) 2시 공개수업 하신다고 통신문 왔어요. 참고만요."),
    ("동호회방", "총무가 7/4(토) 9시 정기산행 인솔한답니다. 참가자만 댓글요."),
]


def neg_rows(pairs, channel, prefix):
    out = []
    for i, (sender, msg) in enumerate(pairs):
        day = BASE_DAYS[i % len(BASE_DAYS)]; hour = 8 + (i % 12)
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{day}T{hour:02d}:{(i*7)%60:02d}:00+09:00",
                    "channel": channel, "sender": sender, "language": "ko",
                    "message": msg, "gold": dict(NEG)})
    return out


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
        "N일+시간없음 행정양성": pos_rows(ADMIN_NDAY_POS, "g17_adminnday"),
        "N일+시간 양성": pos_rows(NDAY_TIME_POS, "g17_ndaytime"),
        "N일까지 마감양성": pos_rows(NDAY_DEADLINE_POS, "g17_ndaydl"),
        "광고 음성": neg_rows(AD_NEG, "kakao", "g17_adneg"),
        "gmail업무 음성": neg_rows(GMAIL_BIZ_NEG, "gmail", "g17_gmailbiz"),
        "재난 음성": neg_rows(DISASTER_NEG, "sms", "g17_disaster"),
        "제3자 음성": neg_rows(THIRD_PARTY_NEG, "kakao", "g17_3rd"),
    }
    rows = [r for g in groups.values() for r in g]
    pos = sum(1 for r in rows if r["gold"]["has_schedule"]); neg = len(rows) - pos
    for name, g in groups.items():
        gp = sum(1 for r in g if r["gold"]["has_schedule"])
        print(f"  {name:18} {len(g):3}  (양성{gp}/음성{len(g)-gp})")
    print(f"  {'합계':18} {len(rows):3}  (양성 {pos} / 음성 {neg}, 음성 {neg/len(rows):.0%})")
    if args.apply:
        p = "data/processed/r17_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
