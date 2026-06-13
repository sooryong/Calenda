"""r30 하드케이스 생성 — r29(Qwen3-0.6B) 실패 진단 타깃.

r29 진단: recall 0.857(놓침 4/28)이 주약점. 놓친 3유형이 전부 '격식 Gmail/마감/단문 종일'
양성인데, specificity 잡으려 부은 격식-Gmail 음성을 Qwen3가 과억제 → 양성까지 놓침.
  · g03 격식 행사 안내(일시 명시)  · g09/g10 마감형 종일  · silup11 단문 종일 task
→ r30 = 이 3유형 양성 복원·증강 + 경계 음성(무일자/지난행사)·광고·@3자 음성 유지(과발화 방지).

설계 원칙:
  · 직접 생성([[feedback_direct_data_gen_over_paid]]), 이름·기관 폭넓게 분산.
  · 표면형은 골든(g03·g09·g10·silup11)과 분리 — 누수 방지.
  · 경계: '구체 미래 일자/마감 있는 안내'=양성, '무일자 회람·자료공유·지난행사'=음성.
  · gold date는 절대일자 또는 N일/N.N 토큰(resolve_when 해석). 마감 시각은 description에(시작 아님).
출력: data/processed/_r30_add.jsonl
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

NAMES = ["서지원","민준호","오채은","배도현","임시연","곽지훈","류서아","천예성","마준영","피현서",
         "복지아","독고민","선우찬","제갈윤","남궁현","사공빈","황보름","어승우","연다흰","표하진"]
ORGS = ["대구테크노파크","경북창조경제혁신센터","한국발명진흥회","중소벤처기업진흥공단","대구디지털혁신진흥원",
        "한국전자통신연구원","대구경북디자인진흥원","한국산업기술기획평가원","경북테크노파크","대구상공회의소",
        "한국지식재산보호원","창업진흥원","한국청년기업가정신재단","대구미래차전환종합지원센터"]
_gi = 0
def nm(k=1):
    global _gi
    out = [NAMES[(_gi + j) % len(NAMES)] for j in range(k)]; _gi += k
    return out if k > 1 else out[0]
_oi = 0
def og():
    global _oi
    o = ORGS[_oi % len(ORGS)]; _oi += 1
    return o

def ev(title, date=None, time=None, end_time=None, all_day=False, location=None,
       attendees=None, organizer=None, description=None, conf=0.9):
    return {"title": title, "date": date, "time": time, "end_time": end_time, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": description, "recurrence": None, "confidence": conf}

def row(sid, recv, ch, sender, msg, has, events, thread=None):
    r = {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
         "language": "ko", "message": msg, "gold": {"has_schedule": has, "events": events}}
    if thread:
        r["thread_context"] = thread
    return r

rows = []

# ── 1) 격식 Gmail 행사 양성 (일시 명시) — g03류 복원. organizer=기관, 시작시각 추출 ──
#   (행사명, 절대일자, time{h,m,marker}, location)
EVENTS = [
    ("창업기업 IR 데모데이", "2026-07-09", {"hour": 2, "minute": 0, "marker": "오후"}, "DIP빌딩 대강당"),
    ("지식재산 실무 세미나", "2026-07-14", {"hour": 10, "minute": 0, "marker": "오전"}, "온라인"),
    ("디지털 전환 컨퍼런스", "2026-07-21", {"hour": 1, "minute": 30, "marker": "오후"}, "엑스코 325호"),
    ("기술사업화 공청회", "2026-08-04", {"hour": 3, "minute": 0, "marker": "오후"}, "온라인"),
    ("청년창업 네트워킹 데이", "2026-07-17", {"hour": 4, "minute": 0, "marker": "오후"}, None),
    ("투자유치 전략 워크숍", "2026-07-25", {"hour": 9, "minute": 30, "marker": "오전"}, "센터 3층 교육장"),
    ("R&D 성과발표회", "2026-08-11", {"hour": 2, "minute": 0, "marker": "오후"}, "온라인"),
    ("스마트팩토리 기술교류회", "2026-07-31", {"hour": 11, "minute": 0, "marker": "오전"}, None),
    ("창업멘토 위촉식", "2026-07-07", {"hour": 5, "minute": 0, "marker": "오후"}, "본관 1층 컨퍼런스홀"),
    ("규제샌드박스 설명회", "2026-08-06", {"hour": 2, "minute": 0, "marker": "오후"}, "온라인"),
    ("ESG 경영 심포지엄", "2026-08-18", {"hour": 1, "minute": 0, "marker": "오후"}, "그랜드호텔 2층"),
    ("수출바우처 사업설명회", "2026-07-23", {"hour": 10, "minute": 0, "marker": "오전"}, "온라인"),
    ("지역혁신 포럼", "2026-08-13", {"hour": 3, "minute": 30, "marker": "오후"}, "시청 별관 대회의실"),
    ("AI 바우처 매칭데이", "2026-07-29", {"hour": 2, "minute": 0, "marker": "오후"}, None),
    ("창업패키지 중간점검 간담회", "2026-08-20", {"hour": 10, "minute": 30, "marker": "오전"}, "온라인"),
    ("특허전략 컨설팅 세미나", "2026-07-11", {"hour": 4, "minute": 0, "marker": "오후"}, "지원센터 2층"),
    ("벤처투자 IR 라운드", "2026-08-27", {"hour": 1, "minute": 0, "marker": "오후"}, "온라인"),
    ("산학협력 기술상담회", "2026-08-25", {"hour": 11, "minute": 0, "marker": "오전"}, None),
]
for i, (name_, dabs, t, loc) in enumerate(EVENTS):
    org = og()
    hh = t["hour"]; mk = t["marker"]; mm = t["minute"]
    tstr = f"{mk} {hh}시" + (f" {mm}분" if mm else "")
    where = "온라인으로" if loc == "온라인" else (f"{loc}에서" if loc else "아래와 같이")
    msg = (f"[{org}] {name_} 개최 안내 — 안녕하세요, {org}입니다. "
           f"{name_}을(를) {where} 진행하오니 많은 참석 바랍니다. 일시: {dabs} {tstr}.")
    rows.append(row(f"r30_evt_{i:02d}", "2026-06-13T11:00:00+09:00", "gmail",
                    f"info{i}@{org[:2]}.or.kr", msg, True,
                    [ev(name_, date=dabs, time=t, location=loc, organizer=org)]))

# ── 2) 마감형 종일 양성 — g09/g10류. all_day, 마감일=date, 마감시각은 description ──
#   (사업명, 마감 절대일자, 마감시각문구 or None, 동작어)
DEADLINES = [
    ("2026년 예비창업패키지 참여기업", "2026-07-10", "18시까지", "모집"),
    ("창업도약패키지 사업화자금 지원", "2026-07-18", "오후 6시까지", "신청"),
    ("지역주력산업 R&D 과제", "2026-08-03", None, "접수"),
    ("청년창업사관학교 입교생", "2026-07-15", "17시까지", "모집"),
    ("기술이전 매칭 지원사업", "2026-08-07", None, "신청"),
    ("수출기업화 바우처 지원", "2026-07-24", "18시까지", "접수"),
    ("스마트공장 구축 지원사업", "2026-08-12", None, "모집"),
    ("창업기업 판로개척 지원", "2026-07-28", "오후 5시까지", "신청"),
    ("지식재산 권리화 비용 지원", "2026-08-19", None, "접수"),
    ("초기창업패키지 후속지원", "2026-07-21", "18시까지", "모집"),
    ("산학연 공동기술개발 과제", "2026-08-24", None, "신청"),
    ("글로벌 액셀러레이팅 참가기업", "2026-08-28", "17시까지", "모집"),
    ("디자인 혁신유망기업", "2026-07-31", None, "접수"),
    ("재직자 직무교육 수강생", "2026-08-14", "오후 6시까지", "신청"),
    ("창업경진대회 출전팀", "2026-08-21", None, "모집"),
]
for i, (biz, dabs, deadline_t, verb) in enumerate(DEADLINES):
    org = og()
    until = f"~{dabs}" + (f" {deadline_t}" if deadline_t else "") + f" {verb}"
    msg = f"[{org}] {biz} {verb} 공고({until}) — {org}에서 {biz}을(를) {verb}합니다. 많은 관심 바랍니다."
    desc = (f"{deadline_t} {verb}") if deadline_t else None
    rows.append(row(f"r30_ddl_{i:02d}", "2026-06-13T10:00:00+09:00", "gmail",
                    f"apply{i}@{org[:2]}.or.kr", msg, True,
                    [ev(f"{biz} {verb} 마감", date=dabs, all_day=True, organizer=org,
                        description=desc, conf=0.82)]))

# ── 3) 단문 종일 task 양성 (SMS) — silup11류. date=N일/N.N 토큰, all_day, 활동=title ──
#   (메시지, gold date 토큰, title, location)
TASKS = [
    ("15일 건강검진 예약 방문", "15일", "건강검진", None),
    ("8일 자격증 시험 접수", "8일", "자격증 시험 접수", None),
    ("22일 차량 정기점검", "22일", "차량 정기점검", None),
    ("3일 전입신고 주민센터", "3일", "전입신고", "주민센터"),
    ("7.18 종합소득세 신고 마감", "7.18", "종합소득세 신고", None),
    ("9일 독감 예방접종", "9일", "독감 예방접종", None),
    ("25일 임대차 계약 갱신", "25일", "임대차 계약 갱신", None),
    ("6.30 재산세 납부 기한", "6.30", "재산세 납부", None),
    ("12일 치과 스케일링 예약", "12일", "치과 스케일링", None),
    ("19일 여권 수령 방문", "19일", "여권 수령", None),
    ("28일 정기 건강검진 재방문", "28일", "건강검진 재방문", None),
    ("8.5 부가가치세 신고", "8.5", "부가가치세 신고", None),
]
for i, (msg, dtok, title, loc) in enumerate(TASKS):
    rows.append(row(f"r30_task_{i:02d}", "2026-06-13T08:30:00+09:00", "sms",
                    f"0102000{i:04d}", msg, True,
                    [ev(title, date=dtok, all_day=True, location=loc, conf=0.85)]))

# ── 4) 경계 음성: 무일자/지난행사 격식 Gmail (양성 늘려도 과발화 안 튀게) ──
NEG_FORMAL = [
    "지난 설명회 발표자료를 공유드립니다. 참석해 주신 분들께 감사드립니다.",
    "분과 운영 관련 회람드리오니 검토 후 회신 부탁드립니다.",
    "2026년도 사업 추진현황 뉴스레터를 발송드립니다. 참고 바랍니다.",
    "위탁정산 절차 안내드립니다. 첨부 양식에 따라 진행 부탁드립니다.",
    "멘토링 결과보고서 양식을 송부드리니 확인 부탁드립니다.",
    "차기 공모사업 관련 추후 별도 안내드릴 예정입니다.",
    "지난주 간담회 회의록을 공유드립니다. 검토 부탁드립니다.",
    "사업 참여기업 대상 만족도 조사 협조 요청드립니다.",
    "행사 관련 사진을 첨부드리니 참고하시기 바랍니다.",
    "교육 수료증 발급 안내드립니다. 마이페이지에서 확인 가능합니다.",
    "협약서 검토 의견 회신 부탁드립니다. 일정은 추후 협의 예정입니다.",
    "분기 실적 보고 양식 변경사항을 안내드립니다.",
    "홈페이지 개편 안내드립니다. 많은 이용 바랍니다.",
    "지난 워크숍 만족도 결과를 공유드립니다.",
    "사업비 집행 지침 개정사항을 회람드립니다.",
    "전문가 자문단 명단을 공유드리니 참고 바랍니다.",
]
for i, m in enumerate(NEG_FORMAL):
    org = og()
    rows.append(row(f"r30_neg_formal_{i:02d}", "2026-06-13T13:00:00+09:00", "gmail",
                    f"staff{i}@{org[:2]}.or.kr", f"[{org}] {m}", False, []))

# ── 5) 광고-with-date 강화 (r29 ad_000 골프조인류 과발화) ──
ADS = [
    ("티오프", "[티오프] 라운딩 조인 요청 ▶ 사파리cc ▶ 7.05(일) 6:40 ▶ 동반자 2분 모십니다. 확인해보세요."),
    ("호텔스컴바인", "[특가] 여름 호캉스 ~7/20(월) 자정까지! 5성급 최대 55% 할인. 지금 예약하세요."),
    ("CGV", "[CGV] 6/27 신작 예매오픈! 지금 예매하면 콤보 50% 할인 이벤트 진행 중."),
    ("올리브영", "[올리브영] 6월 세일 ~6/30까지 전 상품 최대 40%! 매장에서 만나요."),
    ("교보문고", "[교보문고] 7.10까지 여름 독서 캠페인! 2만원 이상 구매 시 사은품 증정."),
    ("쿠팡", "[쿠팡] 오늘 밤 11시까지 와우 회원 단독특가! 지금 담으면 무료배송."),
    ("야놀자", "[야놀자] 워터파크 시즌권 ~8/3 23:59까지 1+1! 한정 수량 마감임박."),
    ("골프존", "[골프존] 6/22 신규 코스 오픈 기념 라운딩권 추첨 이벤트! 응모하세요."),
    ("배달의민족", "[배민] 7/1 오픈 1주년! 오후 6시까지 주문 시 배달비 0원 쿠폰."),
    ("스타벅스", "[스타벅스] 썸머 프로모션 ~7/15 신메뉴 1+1! 가까운 매장에서 즐기세요."),
]
for i, (snd, m) in enumerate(ADS):
    rows.append(row(f"r30_neg_ad_{i:02d}", "2026-06-13T09:00:00+09:00", "kakao", snd, m, False, []))

# ── 6) @3자 의무 음성 (r29 kakao_002 과발화) — 수신자 본인 일정 아님 ──
THIRD = [
    ("운영지원방", "@서지원 7/9(목) 14:00-17:00 부스 운영을 맡아주셔야 하는 상황입니다."),
    ("교육기획방", "@민준호 다음주 수요일 특강 강사로 섭외 진행하셔야 합니다."),
    ("행사총괄방", "@오채은 8/4 공청회 사회는 채은님이 보셔야 할 것 같습니다."),
    ("심사위원방", "@배도현 7/21 평가위원으로 위촉되어 참석하셔야 합니다."),
    ("프로젝트A방", "@임시연 7/15까지 중간보고 발표 준비해주셔야 해요."),
    ("동아리운영방", "@곽지훈 8/11 정기모임 진행 담당으로 배정되셨습니다."),
]
for i, (snd, m) in enumerate(THIRD):
    rows.append(row(f"r30_neg_third_{i:02d}", "2026-06-13T18:30:00+09:00", "kakao", snd, m, False, []))

# ── 라운드트립 검증 (양성 date/time resolve) ──
bad = 0
for r in rows:
    if not r["gold"]["has_schedule"]:
        continue
    for e in r["gold"]["events"]:
        res = resolve_when(r["received_at"], e["date"], e["time"], e["end_time"], e["all_day"])
        if e["date"] and res["start"] is None:
            bad += 1
            print("  ! resolve 실패:", r["scenario_id"], repr(e["date"]))
npos = sum(1 for r in rows if r["gold"]["has_schedule"])
nneg = len(rows) - npos
print(f"생성 {len(rows)}행 (양성 {npos} · 음성 {nneg} = {nneg/len(rows)*100:.0f}% neg) | resolve 실패 {bad}")
out = Path("data/processed/_r30_add.jsonl")
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"→ {out}")
