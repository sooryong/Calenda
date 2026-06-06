"""r16 하드케이스 빌더 — r15 실패분석(real_golden, 디커플링 평가)이 가리킨 2약점 집중.

r15 디커플링 결과: recall 0.955·title 0.90은 충분. 약점은 둘:
  (P) precision — specificity 0.62, 과발화 8건(광고·gmail업무·재난·제3자)이 r15 음성에도 뚫림.
  (T) time/date — 진짜양성 time 0.667. N일 단독·요일토큰·date-only 시간환각·경쟁날짜·멀티턴.

설계 메모:
  - (T) 일부는 resolver 보강과 짝(단독 'N일' 토큰, 요일 별칭). 그래서 양성 gold의 date는 토큰형으로 둠
    ('30일','이번주목')—모델이 계산 않고 토큰만 내도록. resolver가 절대화.
  - deadline all_day↔시각 논쟁은 메트릭 완화로 종결(여기선 안 다룸).
  - 음성은 실제 포맷에 밀착(티샷 불릿·항공 '~날짜 오후N시'·gmail 자료공유/회람/확인/리마인드·CMAS·@제3자).

출력: data/processed/r16_hardcases.jsonl  (assemble_train.py가 'keep'으로 편입)
사용: python scripts/build_r16_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

NEG = {"has_schedule": False, "events": []}
BASE_DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-08", "2026-06-09", "2026-06-10"]


def ev(title, date, *, time=None, all_day=False, location=None, attendees=None,
       organizer=None, confidence=0.85):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": None, "recurrence": None, "confidence": confidence}


# ── (P) 과발화 음성: 실제 뚫린 포맷 밀착 ────────────────────────────────────────────
AD_NEG = [  # 광고/예약 브로드캐스트 (channel=kakao)
    ("티샷", "[티샷] 김영호님에게 골프조인 요청서가 도착했습니다.\n[골프조인 요청내용]\n▶ 레이크사이드\n▶ 6.18(목) 6:24\n▶ 요청회원 굿샷박\n▶ 남녀무관 명랑골퍼 2분 함께해요 ^^\n☞ 지금 요청서를 확인해 보세요\n알림 신청에 의해 발송됩니다."),
    ("티샷", "[티샷] 회원님에게 골프조인 요청서가 도착했습니다.\n▶ 화산cc ▶ 6.22(월) 11:16 ▶ 요청회원 버디퀸\n☞ 요청서를 확인해 보세요. 알림 신청에 의해 발송."),
    ("카카오골프부킹", "[조인모집] 6/27(토) 05:40 사우스링스 1자리! 그린피 16만. 선착순 마감. 채널 차단"),
    ("제주항공", "[제주항공] 여름 운임 특가! 동남아 최대 50% 할인코드.\n■ 진행: ~6월 21일(일) 오후 6시\n■ 출발: ~9/30\n[특가 확인] 수신거부: 채널 차단"),
    ("티웨이항공", "[티웨이] 플라이특가 6/16(화) 오전 10시 오픈! 김포-제주 11,900원~. 예매 ~6/23(화). 무료수신거부"),
    ("여기어때", "[여기어때] 호캉스 타임특가 ~6/19(목) 자정! 5성급 최대 60% 쿠폰. 지금 예약. 채널 차단"),
    ("인터파크투어", "[인터파크] 7월 일본 패키지 얼리버드 D-2! 7/24 출발 오사카 69만원. 마감 ~6/21. 수신거부"),
    ("스타벅스", "[스타벅스] 6월 프리퀀시! ~7/15까지 여름 e스티커 적립하고 굿즈 받으세요. 광고 수신거부"),
    ("현대카드", "(광고) 6월 한정 카드 신규발급 시 10만원 캐시백! ~6/30까지. 무료수신거부 080"),
    ("KB손해보험", "[KB손보] 고객님 자동차보험 만기 D-7! 6/24까지 갱신 시 3만원 캐시백. 상담 신청. 무료수신거부"),
    ("롯데시네마", "[롯데시네마] 6월 영화관람권 1+1 이벤트! ~6/20까지 앱에서 구매. 광고 수신거부"),
    ("배달의민족", "[배민] 단골 쿠폰 도착! 오늘 밤 12시까지 5,000원 할인. 지금 주문. 수신거부"),
]

GMAIL_BIZ_NEG = [  # gmail 업무 음성 (channel=gmail) — 지난행사·회람·확인부탁·리마인드
    ("onestop@kised.or.kr", "[창업진흥원] 전문가 자문단 설명회 자료 공유 — 금일 개최된 설명회에 참석해 주신 분들께 감사드리며 자료를 공유드립니다."),
    ("edu@koef.or.kr", "[KoEF] 프리토타입 강의안 및 실습양식 회람 건 — 위촉 인스트럭터 대상. 검토 후 의견 부탁드립니다."),
    ("jyjeon@koef.or.kr", "[KoEF] 분과 일정 확인 부탁드립니다 — 첨부파일을 확인해 주시고 가능 여부 회신 바랍니다."),
    ("admin@knu.ac.kr", "[리마인드] [경북대 지역전략산업혁신연구소 2차모집 공고] 기술협업 프로젝트 — 관심 기업의 많은 참여 바랍니다."),
    ("secretary@assoc.or.kr", "지난 운영위원회 회의록을 전달드립니다. 검토 후 의견 있으시면 회신 부탁드립니다."),
    ("info@conf2026.org", "컨퍼런스 발표 슬라이드 모음 공유 — 행사에 참여해 주셔서 감사합니다. 자료는 링크에서 확인하세요."),
    ("hr@bigco.com", "[채용] 1차 서류전형 결과 안내 — 합격자께는 개별 연락드립니다. 지원해 주셔서 감사합니다."),
    ("noreply@hometax.go.kr", "[홈택스] 전자세금계산서가 정상 발급되었습니다. 발급 내역은 홈택스에서 확인하실 수 있습니다."),
    ("pm@office.kr", "첨부한 일정표 초안 검토 부탁드립니다 — 조정 필요한 부분 표시해 회신 주세요. 확정은 추후 공지."),
    ("settle@wooricpa.co.kr", "사업비 위탁정산 절차 안내 — 정산 서류 양식과 작성 방법을 첨부와 같이 안내드립니다."),
    ("news@letter.kr", "[위클리 인사이트] 이번 주 추천 아티클 5선과 업계 동향. 구독해 주셔서 감사합니다."),
    ("billing@cloud.com", "6월 클라우드 사용 요금 청구서가 발행되었습니다. 결제 수단을 확인해 주세요."),
]

DISASTER_NEG = [  # 재난·경보 (channel=sms)
    ("#CMAS#Severe", "[기상청] 오늘 16시 호우경보 발효. 하천·계곡 접근 자제, 저지대 침수 주의하세요."),
    ("#CMAS#Emergency", "[행정안전부] 오늘 03:12 충북 괴산 규모 3.5 지진 발생. 여진 주의 바랍니다."),
    ("안전안내문자", "[질병관리청] 폭염경보. 낮 야외활동 자제, 수분 충분히 섭취하세요. 어르신 건강 유의."),
    ("#CMAS#Severe", "[소방청] 오늘 21시 강풍주의보. 간판·창문 등 시설물 점검 바랍니다."),
    ("안전안내문자", "[OO시] 미세먼지 비상저감조치 시행. 차량 2부제 동참, 마스크 착용 바랍니다."),
    ("#CMAS#Emergency", "[경찰청] 6/9 14시경 실종 이OO(8세,여). 마지막 목격 분당. 발견 시 112 신고."),
]

THIRD_PARTY_NEG = [  # 제3자 의무 (channel=kakao)
    ("부트캠프자료방", "@박지훈 강사님 데이터분석 심화 6/27(토) 14:00-18:00 4시간 강의 가능하신지 확인 부탁드립니다."),
    ("운영진방", "@김강사 7/2(수) 10시 특강 진행하셔야 합니다. 자료는 전날까지 부탁드려요."),
    ("프로젝트방", "현우가 6/24(화) 15시에 발주처 미팅 들어간다고 하네요. 우리는 대기만 하면 됩니다."),
    ("팀채널", "지영님이 6/23(월) 오후 반차라 그날 배포는 다른 분이 맡아주셔야 할 것 같아요."),
    ("학부모방", "담임선생님이 6/19(금) 오후 2시에 공개수업 하신다고 통신문 왔어요. 참고만 하세요."),
    ("거래처방", "협력사 정기점검은 6/26(목) 오전 본사 시설팀이 진행한답니다. 우리 쪽 조치는 없어요."),
    ("동호회방", "회장님이 7/5(일) 10시 정기 라이딩 인솔하신답니다. 참가자만 댓글 달아주세요."),
    ("스터디방", "@연우 다음 발표 7/3(목) 8시 네 차례인 거 알지? 준비 잘 해와!"),
]

# ── (T) time/date 양성 ──────────────────────────────────────────────────────────
# 단독 'N일' (gold date=토큰 'N일' — resolver가 가까운 미래로). (channel, sender, msg, ev)
N_DATE_POS = [
    ("sms", "01012345678", "30일 오후1시 미드포인트", ev("미드포인트", "30일", time={"hour": 1, "minute": 0, "marker": "오후"})),
    ("sms", "01055556666", "15일 2시 치과 예약", ev("치과 예약", "15일", time={"hour": 2, "minute": 0, "marker": "오후"})),
    ("sms", "01077778888", "22일 오전 10시 정기검진", ev("정기검진", "22일", time={"hour": 10, "minute": 0, "marker": "오전"})),
    ("kakao", "이대리", "27일 저녁 7시 회식입니다", ev("회식", "27일", time={"hour": 7, "minute": 0, "marker": "저녁"})),
    ("sms", "1668", "3일 14시 차량 정비 예약 확인", ev("차량 정비", "3일", time={"hour": 14, "minute": 0, "marker": None})),
    ("sms", "01033334444", "9일 오후 4시 미용실", ev("미용실", "9일", time={"hour": 4, "minute": 0, "marker": "오후"})),
]

# 요일 토큰 (gold date='이번주X'/'다음주X'). 모델 출력형 다양해도 resolver가 흡수.
WEEKDAY_POS = [
    ("sms", "01038139885", "이번 목요일 19시 화성행 버스예약", ev("화성행 버스", "이번주목", time={"hour": 19, "minute": 0, "marker": None})),
    ("kakao", "민지", "이번 주 토요일 저녁 6시에 보자", ev("약속", "이번주토", time={"hour": 6, "minute": 0, "marker": "저녁"}, attendees=["민지"])),
    ("kakao", "박코치", "다음 주 화요일 오전 11시 코칭 잡을게요", ev("코칭", "다음주화", time={"hour": 11, "minute": 0, "marker": "오전"}, attendees=["박코치"])),
    ("sms", "01099998888", "다음주 금요일 3시 회의실 예약", ev("회의", "다음주금", time={"hour": 3, "minute": 0, "marker": "오후"})),
    ("kakao", "엄마", "이번 일요일 점심에 외식하자", ev("외식", "이번주일", time={"hour": 12, "minute": 0, "marker": None}, all_day=False)),
    ("kakao", "정과장", "다음 수요일 2시 부서 미팅합시다", ev("부서 미팅", "다음주수", time={"hour": 2, "minute": 0, "marker": "오후"}, attendees=["정과장"])),
]

# date-only (시간 환각 금지: time=null, all_day=true). gold date=명시일자(절대).
DATE_ONLY_POS = [
    ("gmail", "shkwon@koef.or.kr", "2025년도 성과공유회 참석 요청 — 일시: 2025년 12월 9일", ev("성과공유회", "2025-12-09", all_day=True, organizer="K-ICT창업멘토링센터", confidence=0.8)),
    ("gmail", "info@conf.org", "추계 학술대회 안내 — 일시: 2026년 6월 20일. 장소는 추후 공지.", ev("추계 학술대회", "2026-06-20", all_day=True, confidence=0.82)),
    ("sms", "01044448888", "6월 18일 가족 모임", ev("가족 모임", "2026-06-18", all_day=True, confidence=0.82)),
    ("gmail", "admin@assoc.or.kr", "정기총회 개최 통지 — 6월 27일 개최 예정입니다. 세부 안건은 첨부 참고.", ev("정기총회", "2026-06-27", all_day=True, confidence=0.8)),
    ("kakao", "동창회", "올해 동창회는 7월 11일입니다. 많이 참석해주세요", ev("동창회", "2026-07-11", all_day=True, confidence=0.8)),
    ("sms", "01022223333", "5월 26일 종소세 신고", ev("종합소득세 신고", "2026-05-26", all_day=True, confidence=0.8)),
]

# 경쟁 날짜: 행사 날짜(괄호 명시) vs 맥락 날짜 — 행사 날짜를 추출.
COMPETING_POS = [
    ("gmail", "onestop@kised.or.kr", "원스톱 지원센터 1차 온라인 설명회(1/28(수), 14시) — 2월 중 플랫폼 운영 개소 예정.",
     ev("1차 온라인 설명회", "2026-01-28", time={"hour": 14, "minute": 0, "marker": None}, location="온라인", organizer="창업진흥원", confidence=0.85)),
    ("gmail", "edu@nipa.kr", "[NIPA] 본 교육은 7월 3일(목) 10시 진행됩니다. 신청은 6월 중 안내 예정.",
     ev("교육", "2026-07-03", time={"hour": 10, "minute": 0, "marker": None}, organizer="정보통신산업진흥원", confidence=0.85)),
    ("gmail", "office@univ.ac.kr", "워크숍 일정 안내 — 행사일: 6월 25일 15시. (접수는 5월 말 마감되었습니다)",
     ev("워크숍", "2026-06-25", time={"hour": 3, "minute": 0, "marker": "오후"}, confidence=0.84)),
    ("kakao", "행사팀", "본 행사는 6/30(월) 오후 2시입니다. 사전모임은 지난주에 끝났어요.",
     ev("행사", "2026-06-30", time={"hour": 2, "minute": 0, "marker": "오후"}, confidence=0.83)),
    ("gmail", "grant@keit.re.kr", "발표회는 7월 8일 14시 개최. 제출 마감은 6월 20일이었습니다.",
     ev("발표회", "2026-07-08", time={"hour": 14, "minute": 0, "marker": None}, confidence=0.84)),
]

# deadline 양성 (g10 놓침 보강) — '~까지' 마감, all_day.
DEADLINE_POS = [
    ("gmail", "jihyeonyu@kban.or.kr", "[엔젤투자허브] 전문개인투자자 양성 교육과정 신청 안내(~10/13 월까지)", ev("전문개인투자자 양성 교육 신청 마감", "2025-10-13", all_day=True, organizer="한국엔젤투자협회", confidence=0.8)),
    ("gmail", "apply@kocca.kr", "[콘텐츠진흥원] 제작지원 신청서 제출 마감 6월 18일까지. 기한 엄수.", ev("제작지원 신청 마감", "2026-06-18", all_day=True, organizer="한국콘텐츠진흥원", confidence=0.82)),
    ("sms", "국세청", "[국세청] 종합소득세 확정신고 기한은 6월 2일까지입니다.", ev("종합소득세 확정신고", "2026-06-02", all_day=True, confidence=0.85)),
    ("gmail", "edu@nipa.kr", "[NIPA] SW마에스트로 연수생 모집 ~6/10(수)까지 접수.", ev("SW마에스트로 모집 마감", "2026-06-10", all_day=True, organizer="정보통신산업진흥원", confidence=0.82)),
    ("sms", "장학재단", "[한국장학재단] 2학기 국가장학금 1차 신청 마감 6월 19일.", ev("국가장학금 신청 마감", "2026-06-19", all_day=True, confidence=0.82)),
    ("gmail", "hr@bigco.com", "[채용] 하계 인턴 지원서 접수 마감 6월 9일까지.", ev("하계 인턴 지원 마감", "2026-06-09", all_day=True, confidence=0.8)),
]

# 멀티턴 확정 (title=활동, 발신자 그룹명/사과맥락 배제). thread + 최종.
MULTITURN_POS = [
    ("2026-05-22T21:57:00+09:00", "정원구 페테리안 초창26탈 경북대",
     [("21:19", "정원구", "멘토님, 오늘 응급환자가 와서 죄송했습니다. 다음주 월 오후 2시 화상미팅 어떠신지요?")],
     "네 감사합니다. 월요일 오후 2시에 뵙겠습니다",
     ev("화상미팅", "다음주월", time={"hour": 2, "minute": 0, "marker": "오후"}, location="온라인", attendees=["정원구"], confidence=0.85)),
    ("2026-06-01T10:39:00+09:00", "김용안 빈체레 초창26탈 경북대",
     [("10:14", "김용안", "6월4일 오전 9시 미팅 어떤지요?"), ("10:35", "김용안", "네 알겠습니다.")],
     "네",
     ev("미팅", "2026-06-04", time={"hour": 9, "minute": 0, "marker": "오전"}, attendees=["김용안"], confidence=0.8)),
    ("2026-06-02T16:00:00+09:00", "한지우 그로스랩 매니저",
     [("15:30", "한지우", "다음주 수요일 2시에 계약 미팅 진행할까요?")],
     "네 그때 뵙겠습니다",
     ev("계약 미팅", "다음주수", time={"hour": 2, "minute": 0, "marker": "오후"}, attendees=["한지우"], confidence=0.84)),
    ("2026-06-03T09:20:00+09:00", "이도윤 팀장",
     [("09:05", "이도윤", "내일 오전 10시나 오후 3시 중 리뷰 미팅 가능할까요?")],
     "오전 10시 좋습니다",
     ev("리뷰 미팅", "내일", time={"hour": 10, "minute": 0, "marker": "오전"}, attendees=["이도윤"], confidence=0.83)),
    # 음성 멀티턴: 최종이 유보 → false
    ("2026-06-02T20:00:00+09:00", "정원구",
     [("19:30", "정원구", "다음주 화요일 3시 미팅 어떠세요?")],
     "음 그날은 어려울 것 같아요. 다시 조율해서 말씀드릴게요", None),
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


def mt_rows(records, prefix):
    out = []
    for i, (recv, sender, thread, final, e) in enumerate(records):
        gold = {"has_schedule": True, "events": [e]} if e else dict(NEG)
        out.append({"scenario_id": f"{prefix}_{i:03d}", "received_at": recv,
                    "channel": "kakao", "sender": sender, "language": "ko",
                    "thread_context": [{"time": t, "sender": s, "message": m} for (t, s, m) in thread],
                    "message": final, "gold": gold})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    groups = {
        "광고 음성": neg_rows(AD_NEG, "kakao", "g16_adneg"),
        "gmail업무 음성": neg_rows(GMAIL_BIZ_NEG, "gmail", "g16_gmailbiz"),
        "재난 음성": neg_rows(DISASTER_NEG, "sms", "g16_disaster"),
        "제3자 음성": neg_rows(THIRD_PARTY_NEG, "kakao", "g16_3rd"),
        "N일 양성": pos_rows(N_DATE_POS, "g16_nday"),
        "요일 양성": pos_rows(WEEKDAY_POS, "g16_weekday"),
        "date-only 양성": pos_rows(DATE_ONLY_POS, "g16_dateonly"),
        "경쟁날짜 양성": pos_rows(COMPETING_POS, "g16_competing"),
        "마감 양성": pos_rows(DEADLINE_POS, "g16_deadline"),
        "멀티턴": mt_rows(MULTITURN_POS, "g16_multiturn"),
    }
    rows = [r for g in groups.values() for r in g]
    pos = sum(1 for r in rows if r["gold"]["has_schedule"]); neg = len(rows) - pos
    for name, g in groups.items():
        gp = sum(1 for r in g if r["gold"]["has_schedule"])
        print(f"  {name:14} {len(g):3}  (양성{gp}/음성{len(g)-gp})")
    print(f"  {'합계':14} {len(rows):3}  (양성 {pos} / 음성 {neg}, 음성 {neg/len(rows):.0%})")

    if args.apply:
        p = "data/processed/r16_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
