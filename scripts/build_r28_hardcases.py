"""r28 하드케이스 생성 — r27 실패 3대 타깃 보강.
  1) 번호목록 그룹 = 1 이벤트 (donggi 분할 회귀 교정)
  2) 발신기관 ≠ 장소 (gmail 발신 org를 location으로 오추출 교정; org는 organizer로)
  3) 과발화 하드네거티브 (일정확인-무일자 · @3자 · 광고-with-date)

직접 생성(메모리: paid 대신 직접 데이터-gen). 이름 폭넓게 분산, 메시지에 요일 미기재(Class-D 회피),
gold date는 절대일자(resolve_when이 그대로 해석). 스키마 11키 완비.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

NAMES = ["김서준","이하은","박지호","최예린","정민재","강수아","조유진","윤도현","임채원","한지우",
         "오세훈","서지안","신예준","권하준","황민서","안소율","송지호","전우진","홍서연","문지율",
         "배현우","조은우","나서윤","구도윤","남시우","유하랑","진예나","방준서","공지민","엄태율"]
_gi = 0
def nm(k):
    global _gi
    out = [NAMES[(_gi+j) % len(NAMES)] for j in range(k)]; _gi += k
    return out

def ev(title, date=None, time=None, end_time=None, all_day=False, location=None,
       attendees=None, organizer=None, description=None):
    return {"title": title, "date": date, "time": time, "end_time": end_time, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": description, "recurrence": None, "confidence": 0.9}

def row(sid, recv, ch, sender, msg, has, events, thread=None):
    r = {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
         "language": "ko", "message": msg, "gold": {"has_schedule": has, "events": events}}
    if thread: r["thread_context"] = thread
    return r

rows = []

# ── 1) 번호목록 그룹 = 1 이벤트 (3~5명, thread에 부분목록 누적) ──
GROUPS = [("동기회","2026-06-16","6/16"),("신년회","2026-07-03","7/3"),("워크샵","2026-06-28","6/28"),
          ("등산 모임","2026-07-12","7/12"),("독서모임","2026-08-09","8/9"),("동문회","2026-06-21","6/21"),
          ("풋살 모임","2026-07-05","7/5"),("연구실 회식","2026-06-25","6/25"),("봉사활동","2026-07-19","7/19"),
          ("과 모임","2026-06-30","6/30")]
for i,(act,dabs,dsurf) in enumerate(GROUPS):
    k = 3 + (i % 3)                       # 3~5명
    mem = nm(k)
    numbered = "\n".join(f"{j+1}. {m}" for j,m in enumerate(mem))
    msg = f"{dsurf} {act} 참석\n{numbered}"
    th = [{"time": "13:2%d" % (i % 9), "sender": mem[0], "message": f"{dsurf} {act} 참석\n1. {mem[0]}\n2. {mem[1]}"}]
    rows.append(row(f"r28_group_{i:02d}", "2026-06-10T13:30:00+09:00", "kakao", mem[-1], msg,
                    True, [ev(act, date=dabs, all_day=True, attendees=mem)], thread=th))

# ── 2) 발신기관 ≠ 장소 (org는 organizer, 장소는 온라인/구체/없음) ──
ORGS = ["창업진흥원","한국엔젤투자협회","지능형자동차부품진흥원","K-ICT창업멘토링센터","경북대학교 창업지원단",
        "대구창조경제혁신센터","한국청년기업가정신재단"]
ORGLOC = [  # (행사명, 절대일자, time, marker, 실제장소)
    ("전문가 자문단 온라인 설명회","2026-06-18",{"hour":2,"minute":0,"marker":"오후"},"온라인"),
    ("창업 멘토링 워크숍","2026-06-24",{"hour":10,"minute":0,"marker":"오전"},None),
    ("투자 설명회","2026-07-02",{"hour":3,"minute":0,"marker":"오후"},"온라인"),
    ("성과공유회","2026-07-08",None,None),
    ("기술교류회","2026-06-27",{"hour":4,"minute":0,"marker":"오후"},"온라인"),
    ("사업화 컨설팅","2026-07-15",{"hour":11,"minute":0,"marker":"오전"},None),
    ("정기 간담회","2026-06-23",{"hour":2,"minute":30,"marker":"오후"},"온라인"),
]
for i,(name_,dabs,t,loc) in enumerate(ORGLOC):
    org = ORGS[i % len(ORGS)]
    when = "온라인으로" if loc == "온라인" else "아래와 같이"
    tstr = "" if t is None else f" 오후 {t['hour']}시" if t["marker"]=="오후" else f" 오전 {t['hour']}시"
    msg = f"[{org}] {name_} 개최 안내 — {org}입니다. {name_}을(를) {when} 진행합니다. 일시: {dabs}{tstr}."
    rows.append(row(f"r28_orgloc_{i:02d}", "2026-06-12T11:00:00+09:00", "gmail", f"no-reply@{i}.or.kr",
                    msg, True, [ev(name_, date=dabs, time=t, all_day=(t is None), location=loc, organizer=org)]))

# ── 3) 과발화 하드네거티브 ──
# 3a) 일정확인-무일자
CONFIRM = ["분과 일정 확인 부탁드립니다. 첨부파일을 확인해 주세요.",
           "진행 방식 관련 자료 회람드립니다. 검토 후 회신 부탁드립니다.",
           "프로젝트 일정표 공유드립니다. 참고 부탁드립니다.",
           "멘토링 진행 관련 문의드립니다. 편하신 시간에 회신 주세요.",
           "행사 안내문 송부드리니 첨부 참고 바랍니다.",
           "보고서 양식 회람 건입니다. 확인 부탁드립니다.",
           "성과평가 서류 추가 안내드립니다. 제출 부탁드립니다."]
for i,m in enumerate(CONFIRM):
    rows.append(row(f"r28_neg_confirm_{i:02d}", "2026-06-11T10:00:00+09:00", "gmail",
                    f"staff@{i}.or.kr", f"[안내] {m}", False, []))
# 3b) @3자 의무 (수신자 본인 일정 아님)
THIRD = [("부트캠프방","@박서준 6/26(금) 13:00-18:00 강의하셔야 하는 상황입니다."),
         ("스터디방","@이하은 다음주 발표 자료 준비하셔야 합니다."),
         ("프로젝트방","@정민재 7/3 워크숍 진행 맡아주셔야 할 것 같아요."),
         ("운영진방","@최예린 6/30 행사 사회 부탁드려야 할 듯합니다."),
         ("동아리방","@강수아 7/10 정기모임 발표자로 섭외되셨습니다.")]
for i,(snd,m) in enumerate(THIRD):
    rows.append(row(f"r28_neg_third_{i:02d}", "2026-06-12T18:00:00+09:00", "kakao", snd, m, False, []))
# 3c) 광고-with-date (브랜드 발신)
ADS = [("티샷","[티샷] 골프조인 요청서 도착 ▶ 그린cc ▶ 7.02(목) 8:10 ▶ 함께하실 분 찾아요. 확인해보세요."),
       ("제주항공","여름특가! 동남아 운임 최대 40% 할인 ~7월 5일(일) 오후 6시까지! 지금 예매하세요."),
       ("롯데시네마","[롯데시네마] 6/20 개봉작 예매 오픈! 지금 예매하면 팝콘 증정 이벤트."),
       ("스타벅스","[스타벅스] 6월 한정 프로모션! ~6/30까지 신메뉴 1+1. 매장에서 만나요."),
       ("야놀자","[야놀자] 여름휴가 특가 ~7/15 23:59까지! 인기 숙소 최대 50% 할인 중."),
       ("배달의민족","[배민] 오늘 저녁 7시까지 쿠폰 할인! 지금 주문하면 배달비 무료.")]
for i,(snd,m) in enumerate(ADS):
    rows.append(row(f"r28_neg_ad_{i:02d}", "2026-06-15T09:00:00+09:00", "kakao", snd, m, False, []))

# 라운드트립 검증 (양성만): gold date/time이 resolve 되는지
bad = 0
for r in rows:
    if not r["gold"]["has_schedule"]: continue
    for e in r["gold"]["events"]:
        res = resolve_when(r["received_at"], e["date"], e["time"], e["end_time"], e["all_day"])
        if e["date"] and res["start"] is None:
            bad += 1; print("  ! resolve 실패:", r["scenario_id"], e["date"])
print(f"생성 {len(rows)}행 (양성 {sum(1 for r in rows if r['gold']['has_schedule'])} · "
      f"음성 {sum(1 for r in rows if not r['gold']['has_schedule'])}) | resolve 실패 {bad}")
Path("data/processed/_r28_add.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print("→ data/processed/_r28_add.jsonl")
