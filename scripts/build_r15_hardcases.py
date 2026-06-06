"""r15 하드케이스 빌더 — r14 실패분석(real_golden 43, final 0.796)이 가리킨 잔존 약점 보강.

r14는 r13 대비 전 지표 상승(time_match 0.535→0.628)했으나 17건이 남았다. 유형:

[음성이 더 필요 — has_schedule_acc 0.791, 여전히 과발화가 1순위]
  ① Gmail 업무메일 과발화 — '정산/처리 안내', '끝난 행사 자료공유', '일정 확인 부탁(첨부)'.
     (g16/g17/g19. r14가 이 하위유형을 넣었지만 일반화가 덜 됨 → 더 다양하게.)
  ② 광고 과발화 — 티샷 '골프조인 요청서' 정확포맷 / 친근체 딜러·보험 영업(명언+권유) / 항공·여행 프로모(~날짜 마감).
     (ad_000/001/002. real_golden의 실제 광고가 여전히 뚫림.)
  ③ 제3자 의무 — "@사람 …하셔야 하는 상황/하신다고" 그룹방 논의. 확정 시각 있어도 내 일정 아님. (kakao_002.)
  ④ 재난·경보 방송 — CMAS 재난문자(산불/지진/실종/호우/폭염). 시각·장소 있어도 일정 아님. (sms_027, 신규 유형.)

[양성인데 추출이 틀림 — time_match 0.628 / location 0.512가 천장]
  ⑤ Gmail 마감=종일 — "~까지 접수/마감" → {all_day:true, time:null}. '교육일정 X / 모집기간 Y'면 교육일정을
     date로(모집마감 시각을 event time으로 넣지 말 것). (g09/g10/g11.)
  ⑥ 환각 억제 양성 — 본문에 없는 장소/참석자/설명을 지어내지 말 것. 특히 유령 '서울대학교 …' 장소, 가짜
     참석자, "스레드 협의 확정" 류 설명. 날짜만 있는 행사는 time/location/attendees 전부 null. (g10/g11/g12.)
  ⑦ Terse SMS 양성 — "5월 26일 종소세 신고"처럼 짧은 '날짜+할일'을 놓치지 말 것(false negative). (sms_001.)
  ⑧ 멀티턴 확정 — 최종 "네/좋습니다"면 직전 제안 시각 추출. title은 활동(미팅/화상미팅)이지 발신자 그룹명
     접미사('초창26탈 경북대')나 사과 맥락('응급동물환자')이 아님. 장소는 명시 없으면 null. (kakao_001/006.)

출력: data/processed/r15_hardcases.jsonl  (assemble_train.py가 'keep' 소스로 편입)
사용:
    python scripts/build_r15_hardcases.py            # 미리보기(건수·균형)
    python scripts/build_r15_hardcases.py --apply     # 파일 기록
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NEG = {"has_schedule": False, "events": []}
BASE_DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-05-28", "2026-05-29", "2026-05-30"]


def ev(title, date, *, time=None, end_time=None, all_day=False,
       location=None, attendees=None, organizer=None, description=None, confidence=0.85):
    return {
        "title": title, "date": date, "time": time, "end_time": end_time,
        "all_day": all_day, "location": location, "attendees": attendees or [],
        "organizer": organizer, "description": description, "recurrence": None,
        "confidence": confidence,
    }


# ── ① Gmail 업무메일 음성 (channel=gmail). 일정처럼 보여도 '내 확정 일정' 아님. ────────────
GMAIL_NEG = [
    # 정산/처리/완료 안내 (g16류)
    ("settle@wooricpa.co.kr", "사업비 위탁정산 절차 안내 — 정산 서류 양식과 작성 방법을 첨부와 같이 안내드리오니 업무에 참조 바랍니다."),
    ("tax@account.co.kr", "[회계법인] 부가가치세 신고 자료 요청 안내 — 정산에 필요한 증빙을 정리해 회신해 주시면 검토 후 진행하겠습니다."),
    ("admin@kised.or.kr", "정산보고서 반려 안내 — 제출하신 정산 서류에 보완이 필요하여 반려되었습니다. 수정 후 재제출 바랍니다."),
    ("noreply@hometax.go.kr", "[홈택스] 전자세금계산서가 정상 발급되었습니다. 발급 내역은 홈택스에서 확인하실 수 있습니다."),
    # 끝난 행사 자료 공유 / 후속 (g17류)
    ("onestop@kised.or.kr", "전문가 자문단 온라인 설명회 자료 공유 — 금일 개최된 설명회에 참석해 주신 분들께 감사드리며 자료를 공유드립니다."),
    ("event@knu.ac.kr", "지난 산학협력 포럼 사진과 발표자료를 공유드립니다. 함께해 주셔서 감사합니다."),
    ("secretary@assoc.or.kr", "어제 진행된 운영위원회 회의 결과를 정리해 전달드립니다. 참고 부탁드립니다."),
    ("info@demoday.kr", "데모데이가 성황리에 마무리되었습니다. 현장 스케치와 수상 결과를 뉴스레터로 전합니다."),
    # 일정 확인 부탁 / 첨부 확인 (g19류 — 확정 시각 없음)
    ("jyjeon@koef.or.kr", "분과 일정 확인 부탁드립니다. 첨부파일을 확인해 주시고 가능 여부 회신 부탁드립니다."),
    ("pm@office.kr", "첨부한 일정표 검토 부탁드립니다. 조정이 필요한 부분 있으면 표시해 회신 주세요."),
    ("coord@center.or.kr", "참석 가능 일자 사전 조사 — 아래 설문으로 가능한 날짜를 표시해 주시면 추후 확정 안내드리겠습니다."),
    ("lead@team.com", "다음 분기 로드맵 초안 공유 — 검토 의견 주시면 반영하겠습니다. 회의는 추후 일정 잡겠습니다."),
]

# ── ② 광고 음성 (channel=kakao). r14에서도 뚫린 실제 포맷 정밀 모사. ────────────────────
AD_NEG = [
    # 티샷 '골프조인 요청서' 정확 포맷
    ("티샷", "[티샷] 고객님에게 골프조인 요청서가 도착했습니다.\n[골프조인 요청내용]\n▶ 남서울cc\n▶ 6.12(금) 6:32\n▶ 요청회원 버디킹\n▶ 남녀무관 명랑골퍼 2분 함께해요 ^^\n☞ 지금 요청서를 확인해 보세요\n해당 알림은 고객님의 알림 신청에 의해 발송됩니다."),
    ("티샷", "[티샷] 회원님에게 골프조인 요청서가 도착했습니다.\n▶ 베어크리크\n▶ 6.15(월) 12:24\n▶ 요청회원 굿샷\n☞ 요청서를 확인해 보세요. 알림 신청에 의해 발송됩니다."),
    ("카카오골프부킹", "[조인모집] 6/20(토) 07:48 스카이72 1자리! 그린피 17만. 신청 선착순 마감. 채널 차단"),
    # 친근체 딜러·보험 영업 (명언 + 권유)
    ("피앤에프 주형호대리", "좋은 아침입니다 대표님^^ 오늘도 응원드립니다!\n실패는 성공의 어머니라 했습니다. 두려워 말고 도전하세요!\n6월 오토플랜 자체 프로모션 안내드립니다. 차량 필요하시면 편하게 연락주세요!"),
    ("현대해상 김설계사", "사장님 행복한 하루 되세요^^\n노력은 배신하지 않습니다!\n자동차보험 만기 다가옵니다. 갱신 상담 원하시면 편히 연락 주세요. 사은품 챙겨드립니다!"),
    ("삼성화재 이팀장", "대표님 좋은 하루입니다! 늘 건강하세요^^\n6월 한정 운전자보험 리뉴얼 안내드립니다. 보장 분석 무료로 도와드리니 연락 주세요."),
    # 항공·여행·쇼핑 프로모 (~날짜 마감 형식 — 마감 시각을 일정으로 오인 금지)
    ("제주항공", "[제주항공] 여름 운임 특가! 동남아 최대 50% 할인코드 제공.\n■ 진행 기간: ~6월 14일(일) 오후 5시\n■ 출발: ~9월 30일\n[특가 확인] 수신거부: 채널 차단"),
    ("진에어", "[진에어] 플라이 특가 오픈! 김포-제주 9,900원~. 예매 ~6/22(일) 23시까지. 무료수신거부"),
    ("야놀자", "[야놀자] 호캉스 타임특가 ~6/18(수) 자정! 5성급 최대 55% 쿠폰. 지금 예약. 채널 차단"),
    ("쿠팡", "[쿠팡] 와우데이 단 하루! 6/16(화) 자정까지 최대 80% 할인. 로켓배송으로 내일 도착. 수신거부"),
    ("스타벅스", "[스타벅스] 6월 프리퀀시 이벤트! 여름 e-프리퀀시 적립하고 굿즈 받으세요. ~7/10까지. 수신거부"),
    ("올리브영", "[올영] 세일 D-1! 6/17(수)까지 전 품목 최대 50%. 멤버십 추가 적립. 광고 수신거부"),
]

# ── ③ 제3자 의무 (channel=kakao). 확정 시각이 있어도 '남의 의무/3자 일정'. ─────────────
THIRD_PARTY = [
    ("부트캠프자료방", "@김현철 아마존 중급 6/26(금) 13:00-18:00까지 5시간 온라인이나 오프라인으로 강의하셔야 하는 상황입니다."),
    ("운영진방", "@박강사 7/2(수) 10시 특강 진행하셔야 합니다. 자료는 전날까지 부탁드려요."),
    ("프로젝트방", "현우가 6/24(화) 15시에 발주처 미팅 들어간다고 하네요. 우리는 대기만 하면 됩니다."),
    ("팀채널", "지영님이 6/23(월) 오후 반차라 그날 점검은 다른 분이 맡아주셔야 할 것 같아요."),
    ("동아리방", "회장이 6/30(월) 19시 정기모임 사회 본다고 합니다. 인원만 집계해 주세요."),
    ("학부모방", "담임선생님이 6/19(금) 오후 2시에 공개수업 하신다고 통신문 왔어요. 참고만 하세요."),
    ("거래처방", "협력사 정기점검은 6/26(목) 오전 본사 시설팀이 진행한답니다. 우리 쪽 조치는 없어요."),
    ("스터디방", "@연우 다음 발표 7/3(목) 8시 네 차례인 거 알지? 준비 잘 해와!"),
]

# ── ④ 재난·경보 방송 음성 (channel=sms, sender=재난문자류). ───────────────────────────
DISASTER_NEG = [
    ("#CMAS#Severe", "오늘 13:06 대구시 동구 도학동 산10-1 산불 발생. 입산 금지. 인근 주민과 등산객은 안전사고에 주의하세요. [대구광역시]"),
    ("#CMAS#Emergency", "[행정안전부] 오늘 02:20 경북 경주 남남서쪽 19km 지역 규모 4.0 지진 발생. 여진 주의, 낙하물 대비 바랍니다."),
    ("#CMAS#Severe", "[기상청] 오늘 15시 호우경보 발효. 하천·계곡 접근 자제, 저지대 침수 주의하세요."),
    ("#CMAS#Emergency", "[경찰청] 6월 3일 09시경 실종 김OO(72세,남). 마지막 목격 안동시 일대. 발견 시 112 신고 바랍니다."),
    ("안전안내문자", "[질병관리청] 폭염경보. 낮 시간대 야외활동 자제, 충분한 수분 섭취하세요. 어르신 건강 유의."),
    ("안전안내문자", "[대구광역시] 미세먼지 비상저감조치 시행. 차량 2부제 동참, 마스크 착용 바랍니다."),
    ("#CMAS#Severe", "[소방청] 오늘 22시 강풍주의보. 간판·창문 등 시설물 점검, 외출 시 주의 바랍니다."),
    ("안전안내문자", "[수자원공사] 6/5 10시 댐 방류 예정. 하류 하천변 출입을 삼가시기 바랍니다."),
]

# ── ⑤ Gmail 마감=종일 양성 (channel=gmail). 명시 날짜·all_day·time=null, 환각 장소 금지. ──
#    (received_at, sender, msg, title, date, organizer)
GMAIL_DEADLINE = [
    ("2025-05-27T10:18:00+09:00", "gamja38@kiapi.or.kr", "[모집공고] 모터소부장 동반성장 활력프로젝트 수혜기업 모집 공고(~6/5(목) 18시까지 접수)", "활력프로젝트 수혜기업 모집 마감", "2025-06-05", "지능형자동차부품진흥원"),
    ("2025-10-10T14:46:00+09:00", "jihyeonyu@kban.or.kr", "[엔젤투자허브] 전문개인투자자 양성 교육과정 신청 안내(~10/13 월까지)", "전문개인투자자 양성 교육 신청 마감", "2025-10-13", "한국엔젤투자협회"),
    ("2025-11-18T13:33:00+09:00", "joo@kiapi.or.kr", "[KIAPI] 자동차 이더넷 재직자 교육 안내 — 모집기간: ~2025.11.30. 18:00, 교육일정: 2025.12.03. ~", "자동차 이더넷 재직자 교육", "2025-12-03", "지능형자동차부품진흥원"),
    ("2026-05-20T09:30:00+09:00", "edu@nipa.kr", "[NIPA] SW마에스트로 연수생 모집 ~6/10(수)까지 온라인 접수. 서류는 포털 업로드.", "SW마에스트로 연수생 모집 마감", "2026-06-10", "정보통신산업진흥원"),
    ("2026-05-22T11:00:00+09:00", "apply@kocca.kr", "[콘텐츠진흥원] 2026 콘텐츠 제작지원 신청서 제출 마감 6월 18일 17시. 기한 엄수.", "콘텐츠 제작지원 신청 마감", "2026-06-18", "한국콘텐츠진흥원"),
    ("2026-05-25T15:20:00+09:00", "grant@keit.re.kr", "[KEIT] 산업기술 R&D 과제 접수 ~6/24(수)까지. 마감 후 제출 불가.", "산업기술 R&D 과제 접수 마감", "2026-06-24", "한국산업기술기획평가원"),
    ("2025-12-01T10:00:00+09:00", "office@univ.ac.kr", "[학사] 2학기 성적 이의신청 기간 ~12/12(금)까지. 기간 내 처리 바랍니다.", "성적 이의신청 마감", "2025-12-12", None),
    ("2026-05-28T13:00:00+09:00", "hr@bigco.com", "[채용] 하계 인턴 지원서 접수 마감 6월 9일 23시59분. 늦은 제출은 인정되지 않습니다.", "하계 인턴 지원 마감", "2026-06-09", None),
]

# ── ⑥ 환각 억제 양성 — 본문에 명시된 것만. 장소·참석자·설명 없으면 전부 null. ───────────
#    (received_at, channel, sender, msg, event_dict)
MINIMAL_POS = [
    ("2025-11-12T11:06:00+09:00", "gmail", "shkwon@koef.or.kr",
     "2025년도 성과공유회 참석 요청 — 성과공유회가 아래와 같이 진행될 예정입니다. 일시: 2025년 12월 9일",
     ev("성과공유회", "2025-12-09", all_day=True, organizer="K-ICT창업멘토링센터", confidence=0.85)),
    ("2026-05-30T09:00:00+09:00", "gmail", "info@conf.org",
     "추계 학술대회 안내 — 일시: 2026년 6월 20일. 장소 등 세부사항은 추후 공지 예정입니다.",
     ev("추계 학술대회", "2026-06-20", all_day=True, confidence=0.82)),
    ("2026-05-26T14:00:00+09:00", "gmail", "admin@assoc.or.kr",
     "정기총회 개최 통지 — 일시: 6월 27일 오후 3시. 안건은 첨부를 참고해 주세요.",
     ev("정기총회", "2026-06-27", time={"hour": 3, "minute": 0, "marker": "오후"}, confidence=0.85)),
    ("2026-06-01T08:30:00+09:00", "sms", "01044448888",
     "6월 12일 치과 예약 잡혔습니다.",
     ev("치과 예약", "2026-06-12", all_day=True, confidence=0.85)),
    ("2026-05-28T19:00:00+09:00", "kakao", "엄마",
     "이번 토요일 저녁 6시에 집에서 외식하자",
     ev("외식", "이번주토", time={"hour": 6, "minute": 0, "marker": "저녁"}, confidence=0.85)),
    ("2026-06-02T10:00:00+09:00", "gmail", "noreply@hospital.kr",
     "[건강검진센터] 예약 확정 안내 — 검진 예약일: 6월 30일 오전 9시. 8시간 금식 후 내원 바랍니다.",
     ev("건강검진", "2026-06-30", time={"hour": 9, "minute": 0, "marker": "오전"}, confidence=0.88)),
    ("2026-05-29T13:00:00+09:00", "sms", "1588",
     "예약하신 미용실 6/7 14시 방문 예정입니다.",
     ev("미용실 예약", "2026-06-07", time={"hour": 14, "minute": 0, "marker": None}, confidence=0.85)),
    ("2026-06-03T09:00:00+09:00", "gmail", "edu@academy.kr",
     "특강 안내 — 6월 21일 14시에 온라인으로 진행됩니다. 링크는 당일 안내드립니다.",
     ev("특강", "2026-06-21", time={"hour": 14, "minute": 0, "marker": None}, location="온라인", confidence=0.85)),
]

# ── ⑦ Terse SMS 양성 — 짧은 '날짜+할일' 놓치지 않기(false negative 방지). ───────────────
TERSE_SMS = [
    ("2026-05-25T01:55:00+09:00", "01038139885", "5월 26일 종소세 신고", ev("종합소득세 신고", "2026-05-26", all_day=True, confidence=0.8)),
    ("2026-06-01T07:30:00+09:00", "01012345678", "6/3 오전 9시 회의", ev("회의", "2026-06-03", time={"hour": 9, "minute": 0, "marker": "오전"}, confidence=0.82)),
    ("2026-06-02T22:10:00+09:00", "01099998888", "내일 10시 병원", ev("병원", "내일", time={"hour": 10, "minute": 0, "marker": None}, confidence=0.82)),
    ("2026-06-04T12:00:00+09:00", "01055556666", "6월 9일 계약서 제출", ev("계약서 제출", "2026-06-09", all_day=True, confidence=0.8)),
    ("2026-05-30T18:00:00+09:00", "01077778888", "모레 3시 미용실", ev("미용실", "모레", time={"hour": 3, "minute": 0, "marker": "오후"}, confidence=0.8)),
    ("2026-06-05T08:00:00+09:00", "01033334444", "6/8 자동차 정기점검", ev("자동차 정기점검", "2026-06-08", all_day=True, confidence=0.8)),
]

# ── ⑧ 멀티턴 확정 — title=활동, 장소 명시 없으면 null, 참석자=상대. ──────────────────────
#    (received_at, sender, thread[list of (time,sender,message)], final_message, event_dict)
MULTITURN_POS = [
    ("2026-05-22T21:57:00+09:00", "정원구 페테리안 초창26탈 경북대",
     [("21:19", "정원구", "멘토님 안녕하세요. 다음주 월 혹은 목요일 오후 2시 중에 화상미팅 어떠신지 확인 부탁드립니다.")],
     "네 감사합니다. 월요일 오후 2시에 뵙겠습니다",
     ev("화상미팅", "다음주월", time={"hour": 2, "minute": 0, "marker": "오후"}, location="온라인", attendees=["정원구"], confidence=0.85)),
    ("2026-06-01T10:39:00+09:00", "김용안 빈체레 초창26탈 경북대",
     [("10:14", "김용안", "6월4일 오전 9시 어떤지요?"), ("10:35", "김용안", "네 알겠습니다.")],
     "네",
     ev("미팅", "2026-06-04", time={"hour": 9, "minute": 0, "marker": "오전"}, attendees=["김용안"], confidence=0.8)),
    ("2026-06-02T16:00:00+09:00", "박서연 코치",
     [("15:30", "박서연", "이번 주 금요일 4시랑 다음 주 화요일 11시 중 편하신 때로 코칭 잡을까요?")],
     "금요일 4시로 할게요",
     ev("코칭", "이번주금", time={"hour": 4, "minute": 0, "marker": "오후"}, attendees=["박서연"], confidence=0.83)),
    ("2026-06-03T09:20:00+09:00", "이도윤 팀장",
     [("09:05", "이도윤", "내일 오전 10시나 오후 3시 중에 리뷰 미팅 가능하실까요?")],
     "오전 10시 좋습니다",
     ev("리뷰 미팅", "내일", time={"hour": 10, "minute": 0, "marker": "오전"}, attendees=["이도윤"], confidence=0.83)),
    ("2026-05-29T13:40:00+09:00", "최민지",
     [("13:10", "최민지", "토요일 저녁에 같이 저녁 먹을까? 6시쯤?")],
     "좋아 토요일 6시에 보자",
     ev("저녁식사", "이번주토", time={"hour": 6, "minute": 0, "marker": "저녁"}, attendees=["최민지"], confidence=0.82)),
    ("2026-06-04T11:00:00+09:00", "한지우 매니저",
     [("10:40", "한지우", "다음주 수요일 2시에 계약 미팅 진행할까요? 장소는 저희 사무실로요.")],
     "네 그때 뵙겠습니다",
     ev("계약 미팅", "다음주수", time={"hour": 2, "minute": 0, "marker": "오후"}, location="사무실", attendees=["한지우"], confidence=0.84)),
    # 음성 멀티턴: 최종이 확정 아님(유보/새 제안) → has_schedule false
    ("2026-06-02T20:00:00+09:00", "정원구",
     [("19:30", "정원구", "다음주 화요일 3시에 미팅 어떠세요?")],
     "음 그날은 어려울 것 같아요. 다시 조율해서 말씀드릴게요",
     None),
    ("2026-06-03T18:00:00+09:00", "김용안",
     [("17:30", "김용안", "내일 점심 같이 하실래요?")],
     "일정 확인하고 다시 연락드릴게요",
     None),
]


def make_neg(pairs, channel, prefix):
    out = []
    for i, (sender, msg) in enumerate(pairs):
        day = BASE_DAYS[i % len(BASE_DAYS)]
        hour = 8 + (i % 12)
        out.append({
            "scenario_id": f"{prefix}_{i:03d}",
            "received_at": f"{day}T{hour:02d}:{(i * 7) % 60:02d}:00+09:00",
            "channel": channel, "sender": sender, "language": "ko",
            "message": msg, "gold": dict(NEG),
        })
    return out


def make_deadline(records, prefix):
    out = []
    for i, (received_at, sender, msg, title, date, organizer) in enumerate(records):
        e = ev(title, date, all_day=True, organizer=organizer, confidence=0.88)
        out.append({
            "scenario_id": f"{prefix}_{i:03d}", "received_at": received_at,
            "channel": "gmail", "sender": sender, "language": "ko",
            "message": msg, "gold": {"has_schedule": True, "events": [e]},
        })
    return out


def make_minimal(records, prefix):
    out = []
    for i, (received_at, channel, sender, msg, e) in enumerate(records):
        out.append({
            "scenario_id": f"{prefix}_{i:03d}", "received_at": received_at,
            "channel": channel, "sender": sender, "language": "ko",
            "message": msg, "gold": {"has_schedule": True, "events": [e]},
        })
    return out


def make_terse(records, prefix):
    out = []
    for i, (received_at, sender, msg, e) in enumerate(records):
        out.append({
            "scenario_id": f"{prefix}_{i:03d}", "received_at": received_at,
            "channel": "sms", "sender": sender, "language": "ko",
            "message": msg, "gold": {"has_schedule": True, "events": [e]},
        })
    return out


def make_multiturn(records, prefix):
    out = []
    for i, (received_at, sender, thread, final_msg, e) in enumerate(records):
        thread_ctx = [{"time": t, "sender": s, "message": m} for (t, s, m) in thread]
        gold = {"has_schedule": True, "events": [e]} if e else dict(NEG)
        out.append({
            "scenario_id": f"{prefix}_{i:03d}", "received_at": received_at,
            "channel": "kakao", "sender": sender, "language": "ko",
            "thread_context": thread_ctx, "message": final_msg, "gold": gold,
        })
    return out


def write(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    gmail_neg = make_neg(GMAIL_NEG, "gmail", "g15_gmailneg")
    ad_neg = make_neg(AD_NEG, "kakao", "g15_adneg")
    third = make_neg(THIRD_PARTY, "kakao", "g15_3rdparty")
    disaster = make_neg(DISASTER_NEG, "sms", "g15_disaster")
    deadline = make_deadline(GMAIL_DEADLINE, "g15_deadline")
    minimal = make_minimal(MINIMAL_POS, "g15_minimal")
    terse = make_terse(TERSE_SMS, "g15_terse")
    multiturn = make_multiturn(MULTITURN_POS, "g15_multiturn")

    rows = gmail_neg + ad_neg + third + disaster + deadline + minimal + terse + multiturn
    pos = sum(1 for r in rows if r["gold"]["has_schedule"])
    neg = len(rows) - pos

    print(f"① Gmail 업무 음성:   {len(gmail_neg)}")
    print(f"② 광고 음성:         {len(ad_neg)}")
    print(f"③ 제3자 음성:        {len(third)}")
    print(f"④ 재난·경보 음성:    {len(disaster)}")
    print(f"⑤ Gmail 마감=종일:   {len(deadline)} (양성)")
    print(f"⑥ 환각억제 양성:     {len(minimal)} (양성)")
    print(f"⑦ Terse SMS 양성:    {len(terse)} (양성)")
    print(f"⑧ 멀티턴:            {len(multiturn)} (양성{sum(1 for r in multiturn if r['gold']['has_schedule'])}/음성{sum(1 for r in multiturn if not r['gold']['has_schedule'])})")
    print(f"합계:                {len(rows)}  (양성 {pos} / 음성 {neg}, 음성 {neg/len(rows):.0%})")

    if args.apply:
        write("data/processed/r15_hardcases.jsonl", rows)
        print("→ data/processed/r15_hardcases.jsonl")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
