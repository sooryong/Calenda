"""r31 하드케이스 생성 — '장소를 제목에 합성 + 신뢰도 장소 의존 제거' 설계 타깃.

배경(2026-06-14 실사용): "내일 13시 AWS 교육팀과 줌 미팅" → 모델이 location:null로 **'줌'을 통째 누락**.
원인 = 학습셋에 명명된 온라인 도구(줌·구글밋·팀즈·전화)가 location으로 박힌 양성이 과소(25건).
신설계: 온라인 도구도 location으로 추출(앱 compose_title이 '@줌'으로 제목에 합성 + 캘린더 장소칸).

이 라운드 데이터:
  1) 온라인-도구 미팅 양성 — gold.location = 도구명(줌/구글밋/팀즈/웹엑스/전화/페이스타임…). date+time+활동 분명 → conf 0.90+(장소 무관 새 루브릭).
  2) 물리-장소 양성(소량) — 장소 추출 + 새 루브릭 confidence 재확인.
  3) 온라인-도구 하드네거티브 — '줌 업데이트/요금/사용법' 등 도구명만 등장, 일정 아님(has_schedule:false). 키워드 과발화 방지.

원칙: 직접 생성([[feedback_direct_data_gen_over_paid]]), 이름/활동/도구 분산, 골든과 표면형 분리(누수 방지).
출력: data/processed/_r31_add.jsonl  (build_r30처럼 train.jsonl에 append)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

NAMES = ["한도경","서윤하","민세아","조하람","구본우","나예준","심도윤","양가온","우진서","표연우",
         "방시현","공하늘","육선재","빈도하","석유나","탁민재","하서진","온유빈","좌도현","범지우"]
ORGS = ["넥서스소프트","미래로보틱스","그린에너지랩","바이오메드코리아","스마트시티테크","클라우드웍스",
        "에이아이비전","디지털커머스","핀테크솔루션","모빌리티랩","헬스케어플러스","에듀테크원"]
_ni = 0
def nm(k=1):
    global _ni
    out = [NAMES[(_ni + j) % len(NAMES)] for j in range(k)]; _ni += k
    return out if k > 1 else out[0]
_oi = 0
def og():
    global _oi
    o = ORGS[_oi % len(ORGS)]; _oi += 1
    return o

def ev(title, date=None, time=None, end_time=None, all_day=False, location=None,
       attendees=None, organizer=None, description=None, conf=0.92):
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

# ── 1) 온라인-도구 미팅 양성 ──────────────────────────────────────────────
#   (활동, date토큰, time{h,m,marker}, 도구(location), 참석자수, 채널, 발신자형)
#   발신자형: 'self'=내가 보낸 SMS(발신표시 없음), 'name'=사람, 'org'=기관메일
ONLINE = [
    ("주간회의",        "내일",        {"hour": 3,  "minute": 0,  "marker": "오후"}, "줌",       1, "kakao", "name"),
    ("미팅",            "내일",        {"hour": 1,  "minute": 0,  "marker": "오후"}, "줌",       1, "sms",   "self"),
    ("신규입사자 인터뷰", "다음주화",     {"hour": 10, "minute": 0,  "marker": None},   "구글밋",   2, "gmail", "org"),
    ("제품 데모",       "모레",        {"hour": 4,  "minute": 0,  "marker": "오후"}, "팀즈",     1, "kakao", "name"),
    ("킥오프",          "다음주수",     {"hour": 11, "minute": 0,  "marker": "오전"}, "줌",       2, "gmail", "org"),
    ("화상 상담",       "내일",        {"hour": 2,  "minute": 30, "marker": "오후"}, "전화",     0, "sms",   "self"),
    ("디자인 리뷰",     "이번주금",     {"hour": 5,  "minute": 0,  "marker": "오후"}, "피그마 회의", 1, "kakao", "name"),
    ("주간 동기화 회의", "다음주월",     {"hour": 9,  "minute": 30, "marker": "오전"}, "구글밋",   2, "gmail", "org"),
    ("기술 면접",       "3일후",       {"hour": 2,  "minute": 0,  "marker": "오후"}, "웹엑스",   1, "gmail", "org"),
    ("멘토링",          "내일",        {"hour": 7,  "minute": 0,  "marker": "저녁"}, "줌",       1, "kakao", "name"),
    ("투자 미팅",       "다음주목",     {"hour": 3,  "minute": 0,  "marker": "오후"}, "줌",       2, "gmail", "org"),
    ("스프린트 회고",   "모레",        {"hour": 10, "minute": 0,  "marker": "오전"}, "팀즈",     2, "kakao", "name"),
    ("고객 미팅",       "내일",        {"hour": 4,  "minute": 30, "marker": "오후"}, "구글밋",   1, "sms",   "self"),
    ("원격 점검",       "이번주목",     {"hour": 11, "minute": 0,  "marker": "오전"}, "팀즈",     1, "gmail", "org"),
    ("화상 회의",       "다음주화",     {"hour": 2,  "minute": 0,  "marker": "오후"}, "줌",       3, "kakao", "name"),
    ("온라인 강의",     "2일후",       {"hour": 8,  "minute": 0,  "marker": "저녁"}, "줌",       0, "sms",   "self"),
    ("협력사 미팅",     "다음주금",     {"hour": 1,  "minute": 30, "marker": "오후"}, "웹엑스",   2, "gmail", "org"),
    ("코드 리뷰 세션",  "내일",        {"hour": 3,  "minute": 0,  "marker": "오후"}, "구글밋",   1, "kakao", "name"),
    ("전화 상담",       "모레",        {"hour": 10, "minute": 30, "marker": "오전"}, "전화",     0, "sms",   "self"),
    ("화상 인터뷰",     "다음주수",     {"hour": 2,  "minute": 0,  "marker": "오후"}, "페이스타임", 1, "kakao", "name"),
    ("정기 보고",       "이번주금",     {"hour": 4,  "minute": 0,  "marker": "오후"}, "팀즈",     1, "gmail", "org"),
    ("제휴 논의",       "내일",        {"hour": 11, "minute": 0,  "marker": "오전"}, "줌",       1, "kakao", "name"),
    ("세미나",          "다음주화",     {"hour": 2,  "minute": 0,  "marker": "오후"}, "유튜브 라이브", 0, "gmail", "org"),
    ("팀 미팅",         "내일",        {"hour": 5,  "minute": 0,  "marker": "오후"}, "구글밋",   2, "sms",   "self"),
]
ACT_PREFIX = {"name": "", "self": "", "org": ""}
for i, (act, d, t, tool, natt, ch, sform) in enumerate(ONLINE):
    hh, mm, mk = t["hour"], t["minute"], t["marker"]
    dword = {"내일": "내일", "모레": "모레", "다음주월": "다음주 월요일", "다음주화": "다음주 화요일",
             "다음주수": "다음주 수요일", "다음주목": "다음주 목요일", "다음주금": "다음주 금요일",
             "이번주목": "이번주 목요일", "이번주금": "이번주 금요일", "2일후": "2일 뒤", "3일후": "3일 뒤"}[d]
    tword = (f"{mk} " if mk else "") + f"{hh}시" + (f" {mm}분" if mm else "")
    atts = nm(natt) if natt else []
    atts = atts if isinstance(atts, list) else [atts]
    who = (" ".join(atts) + "님과 ") if atts else ""
    body = f"{dword} {tword} {tool}으로 {who}{act} 진행하겠습니다."
    if sform == "self":
        sender, msg = "나", f"{dword} {tword} {tool} {act}"
    elif sform == "name":
        snm = nm(); sender = snm; msg = f"{snm}입니다. {body}"
    else:
        org = og(); sender = f"pm@{org[:3]}.com"; msg = f"[{org}] {body} 링크는 추후 공유드립니다."
    conf = 0.95 if (mk and mm == 0) else 0.92
    rows.append(row(f"r31_online_{i:02d}", "2026-06-14T09:00:00+09:00", ch, sender, msg, True,
                    [ev(act, date=d, time=t, location=tool, attendees=atts, conf=conf)]))

# ── 2) 물리-장소 양성(소량) — 장소 추출 + 새 루브릭 confidence 재확인 ──────────
PHYS = [
    ("점심 미팅",   "내일",     {"hour": 12, "minute": 0, "marker": None},   "강남역 2번출구", 1, "kakao", "name"),
    ("저녁식사",    "모레",     {"hour": 7,  "minute": 0, "marker": "저녁"}, "홍대 거리",     1, "sms",   "self"),
    ("현장 점검",   "다음주화",  {"hour": 10, "minute": 0, "marker": "오전"}, "성수동 공장",   2, "gmail", "org"),
    ("진료",       "다음주수",  {"hour": 3,  "minute": 30, "marker": "오후"}, "서울내과",     0, "sms",   "org2"),
    ("워크숍",     "다음주금",  {"hour": 9,  "minute": 0, "marker": "오전"}, "양재 교육장",   2, "gmail", "org"),
    ("커피챗",     "내일",     {"hour": 4,  "minute": 0, "marker": "오후"}, "역삼 스타벅스", 1, "kakao", "name"),
]
for i, (act, d, t, loc, natt, ch, sform) in enumerate(PHYS):
    hh, mm, mk = t["hour"], t["minute"], t["marker"]
    dword = {"내일": "내일", "모레": "모레", "다음주화": "다음주 화요일", "다음주수": "다음주 수요일",
             "다음주금": "다음주 금요일"}[d]
    tword = (f"{mk} " if mk else "") + f"{hh}시" + (f" {mm}분" if mm else "")
    atts = nm(natt) if natt else []
    atts = atts if isinstance(atts, list) else [atts]
    who = (" ".join(atts) + "님과 ") if atts else ""
    org = None
    if sform == "self":
        sender, msg = "나", f"{dword} {tword} {loc}에서 {act}"
    elif sform == "name":
        snm = nm(); sender = snm; msg = f"{snm}입니다. {dword} {tword} {loc}에서 {who}{act} 어때요?"
    elif sform == "org2":
        sender = loc; msg = f"[{loc}] {dword} {tword} {act} 예약 확인 안내드립니다."; org = loc
    else:
        org = og(); sender = f"info@{org[:3]}.com"; msg = f"[{org}] {dword} {tword} {loc}에서 {act} 진행합니다."
    rows.append(row(f"r31_phys_{i:02d}", "2026-06-14T09:30:00+09:00", ch, sender, msg, True,
                    [ev(act, date=d, time=t, location=loc, attendees=atts, organizer=org, conf=0.95)]))

# ── 3) 온라인-도구 하드네거티브 — 도구명만 등장, 일정 아님 ──────────────────────
NEG = [
    ("kakao", "공지방",   "줌 5.17 버전 업데이트 안내입니다. 보안 패치가 포함되어 있으니 업데이트 바랍니다."),
    ("gmail", "billing@zoom", "[Zoom] 유료 요금제 갱신 안내 — 다음 결제일에 자동 청구됩니다."),
    ("kakao", "IT지원방", "구글밋 사용 가이드 영상 공유합니다. 처음 쓰시는 분 참고하세요."),
    ("sms",   "15880000", "[Microsoft] Teams 로그인 알림: 새 기기에서 접속되었습니다."),
    ("gmail", "no-reply@webex", "웹엑스 신규 기능 소개 뉴스레터를 보내드립니다."),
    ("kakao", "총무방",   "줌 계정 라이선스 추가 구매 건 결재 올렸습니다. 확인 부탁드려요."),
    ("sms",   "15990000", "[Zoom] 인증코드는 482913 입니다. 타인에게 알려주지 마세요."),
    ("gmail", "edu@meet", "구글밋 단축키 모음 자료를 첨부합니다. 업무에 활용하세요."),
    ("kakao", "장비방",   "회의실 팀즈 룸 시스템 점검은 지난주에 완료했습니다."),
    ("sms",   "나",       "줌 링크 클릭이 안 되는데 혹시 새 버전 받아야 하나요?"),
    ("gmail", "promo@zoom", "줌 웨비나 기능 30일 무료 체험 프로모션 안내드립니다."),
    ("kakao", "스터디방", "지난번 줌 강의 녹화본 링크 다시 올려요. 복습용입니다."),
]
for i, (ch, snd, m) in enumerate(NEG):
    rows.append(row(f"r31_neg_online_{i:02d}", "2026-06-14T10:00:00+09:00", ch, snd, m, False, []))

# ── 4) r30 골든 실패 보완 ───────────────────────────────────────────────
# 4-A) 제3자 의무 부여 음성 (kakao_real_002: '@이름 …하셔야 하는 상황입니다' 과발화)
THIRD = [
    ("자료정리방", "@{n} 아마존 중급 7/3(금) 13:00-18:00 5시간 온라인이나 오프라인으로 강의하셔야 하는 상황입니다."),
    ("운영지원방", "@{n} 다음주 화 오후 2시 신입 OJT 진행하셔야 합니다. 자료 미리 준비해 주세요."),
    ("행사기획방", "@{n} 8/5 공청회 사회는 {n2}님이 보셔야 할 것 같아요."),
    ("교육팀방",   "@{n} 7/10 워크숍 발표 세션 맡으셔야 하는데 가능하신가요?"),
    ("심사방",     "@{n} 7/22 13시 평가위원으로 참석하셔야 합니다."),
    ("프로젝트방", "@{n} 6/30까지 중간보고 PT 준비하셔야 해요."),
    ("스터디방",   "@{n} 다음주 수 저녁 8시 발제 담당이세요. 챕터3 정리 부탁."),
    ("총무방",     "@{n} 7/18 정기총회 진행 맡으셔야 합니다. 시나리오 공유드릴게요."),
]
for i, (snd, tmpl) in enumerate(THIRD):
    m = tmpl.replace("{n2}", nm()).replace("{n}", nm())
    rows.append(row(f"r31_neg_third_{i:02d}", "2026-06-14T18:00:00+09:00", "kakao", snd, m, False, []))

# 4-B) 서비스 알림/초대 광고 음성 (ad_gold_000: '[티샷] 요청서 도착 ▶날짜 시간' 과발화)
SVC = [
    ("티샷",     "[티샷] {n}님에게 골프조인 요청서가 도착했습니다.\n▶ 레이크사이드cc\n▶ 7.14(화) 6:50\n▶ 남녀무관 2분 함께해요 ^^\n☞ 지금 요청서를 확인하세요"),
    ("프렌즈모임", "[프렌즈] {n}님, 새로운 모임 초대장이 도착했어요!\n▶ 강남 보드게임카페\n▶ 7.20(일) 19:00\n앱에서 참여 여부를 선택해주세요."),
    ("테니스매칭", "[매치업] {n}님에게 복식 매칭 요청이 왔습니다.\n▶ 양재 테니스장\n▶ 7.12(토) 8:00\n수락하시려면 앱을 열어주세요."),
    ("소셜다이닝", "[소셜다이닝] {n}님, 관심 모임이 곧 마감돼요.\n▶ 이태원 와인바\n▶ 7.16(수) 20:00\n지금 신청 →"),
    ("등산크루",  "[크루] {n}님에게 산행 번개 알림이 도착했습니다.\n▶ 북한산 우이역 집결\n▶ 7.19(토) 7:30\n참여 버튼을 눌러주세요."),
    ("러닝앱",    "[런데이] {n}님, 주변 러닝 크루 모집 중!\n▶ 한강 반포\n▶ 7.13(일) 6:00\n앱에서 합류하기"),
]
for i, (snd, tmpl) in enumerate(SVC):
    rows.append(row(f"r31_neg_svc_{i:02d}", "2026-06-14T09:00:00+09:00", "kakao", snd, tmpl.replace("{n}", nm()), False, []))

# 4-C) 멀티턴 확정 — 발신자명에 소속/모임 토큰, '네'류 확정 시 thread에서 추출(발신자 노이즈 무시)
#   (kakao_real_006/001: 발신자 '…초창26탈 경북대'에서 title/loc 날조, 온라인 장소 누락 교정)
CONFIRM = [
    # (소속붙은발신자, 제안메시지, 확정메시지, gold활동, date, time, location)
    ("정한울 페테리안 초창26탈 경북대", "다음주 화요일 오후 3시 줌으로 화상미팅 어떠세요?", "네 좋습니다 그때 뵐게요",
     "화상미팅", "다음주화", {"hour": 3, "minute": 0, "marker": "오후"}, "줌"),
    ("김도언 빈체레 36기 한양대", "월요일 오후 2시에 화상으로 미팅 가능하실까요?", "네 감사합니다 월요일 오후 2시에 뵙겠습니다",
     "미팅", "다음주월", {"hour": 2, "minute": 0, "marker": "오후"}, "온라인"),
    ("배수아 그린랩 21학번 부산대", "내일 오전 11시 구글밋으로 회의 잡을까요?", "넵 그때 들어갈게요",
     "회의", "내일", {"hour": 11, "minute": 0, "marker": "오전"}, "구글밋"),
    ("한지호 동기회 총무 영남대", "모레 저녁 7시 강남에서 모임 어때?", "좋아 그때 보자",
     "모임", "모레", {"hour": 7, "minute": 0, "marker": "저녁"}, "강남"),
    ("오세린 스타트업클럽 17기 고려대", "다음주 목 오후 4시 팀즈로 점검 미팅 하시죠", "네 그렇게 하겠습니다",
     "점검 미팅", "다음주목", {"hour": 4, "minute": 0, "marker": "오후"}, "팀즈"),
    ("문가람 독서모임 운영진 연세대", "이번주 금요일 저녁 8시 전화로 짧게 논의해요", "네 전화 드릴게요",
     "논의", "이번주금", {"hour": 8, "minute": 0, "marker": "저녁"}, "전화"),
]
for i, (snd, prop, conf_msg, act, d, t, loc) in enumerate(CONFIRM):
    pname = snd.split()[0]  # 발신자 표시명(소속 토큰 제외) — attendees엔 이름만
    thread = [{"time": "10:00", "sender": pname, "message": prop},
              {"time": "10:05", "sender": "나", "message": "확인해볼게요"}]
    rows.append(row(f"r31_confirm_{i:02d}", "2026-06-14T10:10:00+09:00", "kakao", snd, conf_msg, True,
                    [ev(act, date=d, time=t, location=loc, attendees=[pname], conf=0.9)], thread=thread))

# 4-D) 격식 행사 제목충실 — 긴 프로그램명에서 핵심 활동만 (gmail_gov_g01: '모두의 창업 1기 출범식'→'출범식')
FORMAL = [
    ("「청년창업 사관학교」 2기 입교식", "입교식", "2026-07-08", {"hour": 2, "minute": 0, "marker": "오후"}, "본관 대강당"),
    ("「모두의 창업」 1기 오리엔테이션", "오리엔테이션", "2026-07-15", {"hour": 10, "minute": 0, "marker": "오전"}, "글로벌플라자"),
    ("「지역혁신 리더」 3기 발대식", "발대식", "2026-07-22", {"hour": 3, "minute": 0, "marker": "오후"}, "시청 대회의실"),
    ("「창업도약패키지」 성과공유회", "성과공유회", "2026-08-05", {"hour": 1, "minute": 30, "marker": "오후"}, "엑스코"),
    ("「스마트제조 혁신」 워크숍 1차", "워크숍", "2026-07-29", {"hour": 9, "minute": 30, "marker": "오전"}, "교육장"),
    ("「예비창업 패키지」 최종 점검회의", "점검회의", "2026-08-12", {"hour": 4, "minute": 0, "marker": "오후"}, None),
]
for i, (prog, core, dabs, t, loc) in enumerate(FORMAL):
    org = og()
    tword = (f"{t['marker']} " if t['marker'] else "") + f"{t['hour']}시" + (f" {t['minute']}분" if t['minute'] else "")
    where = f"{loc}에서" if loc else "아래와 같이"
    msg = (f"안녕하십니까. {org}입니다. {prog}을(를) {where} 진행하오니 참석 부탁드립니다. 일시: {dabs} {tword}.")
    rows.append(row(f"r31_formal_{i:02d}", "2026-06-14T11:00:00+09:00", "gmail",
                    f"info@{org[:3]}.or.kr", msg, True,
                    [ev(core, date=dabs, time=t, location=loc, organizer=org, conf=0.93)]))

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
out = Path("data/processed/_r31_add.jsonl")
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"→ {out}")
