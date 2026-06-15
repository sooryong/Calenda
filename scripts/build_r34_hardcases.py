"""r34 하드케이스 — r33 실사용 실패 처방 (실카톡 분포 메우기).

r33 실사용 진단(동일 입력 재추론): golden 0.944지만 실제 카톡에서 과발화·환각 지속.
  - 서비스/금융 알림(카카오페이 적립·스타벅스 결제·카드 승인)을 일정으로 등록 → 음성 필요.
  - 영업 로지스틱스("오후에 연락드리겠습니다", "견적 보내드립니다")를 일정으로 → 음성 필요.
  - 인사말/안부(월요일 아침 인사)를 일정으로 → 음성 필요.
  - 긴 행사명에 무시간 시각 환각 + 제목→location 복제(대구TP) → time:null·location:null 양성 필요.
  - 지나가는 행사 언급("내일 간담회 있어 정신없을듯")을 일정으로 → 음성 필요.

원칙: 실제 메시지를 verbatim 복사하지 않음(골든 누수·과적합 방지) — 같은 '구조'의 합성 변형.
실제 실패 메시지는 data/eval/golden.jsonl에 held-out으로 별도 추가(eval이 실분포 측정).
출력: data/processed/_r34_add.jsonl   (= prompts/schema.md)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

T = lambda h, m, mk: {"hour": h, "minute": m, "marker": mk}


def neg(sid, recv, sender, msg, ch="kakao", thread=None):
    r = {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
         "language": "ko", "message": msg, "gold": {"has_schedule": False, "events": []}}
    if thread:
        r["thread_context"] = thread
    return r


def ev(title, date, time, location=None, attendees=None, all_day=False, desc=None, conf=0.85):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": None,
            "description": desc, "recurrence": None, "confidence": conf}


def pos(sid, recv, sender, msg, events, ch="kakao", thread=None):
    r = {"scenario_id": sid, "received_at": recv, "channel": ch, "sender": sender,
         "language": "ko", "message": msg, "gold": {"has_schedule": True, "events": events}}
    if thread:
        r["thread_context"] = thread
    return r


RECV = "2026-06-15T10:00:00+09:00"  # 월
rows = []

# ── A. 금융/서비스 알림 음성 (카드·페이·멤버십·구독·포인트) ─────────────────────
A = [
    ("카카오페이", "카카오페이 트래블로그 체크카드 이용으로 128P를 받았어요.\n\n- 적립일시 : 2026. 6. 15.(월) 11:20\n- 사용기한 : 2028. 6. 30.(금) 23:59\n- 카드명 : 카카오페이 트래블로그 체크카드"),
    ("토스", "토스머니 3,000원이 충전되었습니다. 잔액 12,400원."),
    ("KB국민은행", "[KB]변*룡님 06/15 14:32\n출금 50,000원\n잔액 1,240,300원\n현대카드결제"),
    ("신한카드", "[신한카드 승인] 변*룡님\n12,800원 일시불\n06/15 12:10 스타벅스 대구신천DT"),
    ("Starbucks Korea", "변*룡 님!\nBuddy Pass 이용료가 정기 결제될 예정입니다.\n\n- 정기 결제 예정일 : 2026.07.17\n- 정기 결제 예정 금액: 7,900원\n\n결제를 원하지 않으실 경우 미리 해지 신청을 해주세요."),
    ("Starbucks Korea", "변*룡 님, 유효기간이 30일 미만인 별에 대해 안내드립니다.\n▶ 소멸 예정 별 : 3개\n▶ 소멸 예정 기간 : 2026-06-20 ~ 2026-07-19"),
    ("Starbucks Korea", "대구신천DT 픽업대에서 기다리고있어요. (A-77)"),
    ("쿠팡", "[쿠팡] 주문하신 상품이 배송 출발했습니다. 오늘 도착 예정입니다."),
    ("SKT", "[SKT] 6월 청구요금 안내\n청구금액 : 55,000원\n납부예정일 : 2026.06.25"),
    ("넷플릭스", "Netflix 멤버십 요금이 결제되었습니다. 다음 결제일은 2026.07.15입니다."),
    ("현대카드", "[현대카드] 결제예정금액 안내\n6월 결제예정 : 432,000원\n결제일 : 2026.07.01"),
    ("배달의민족", "[배민] 리뷰 작성하고 5,000원 쿠폰 받으세요! 지난 주문 어떠셨나요?"),
    ("CJ대한통운", "고객님의 택배가 오늘 배송될 예정입니다. 부재 시 경비실에 보관됩니다."),
    ("카카오페이", "이번 달 카카오페이 혜택 리포트가 도착했어요. 적립 내역을 확인해보세요."),
]
for i, (snd, msg) in enumerate(A):
    rows.append(neg(f"r34_svc_{i:02d}", RECV, snd, msg))

# ── B. 영업/상담 로지스틱스 음성 (연락·견적·검토 약속은 일정 아님) ───────────────
B = [
    ("렌터카 상담 박매니저", "오후 늦게 다시 연락드리겠습니다!",
     [{"time": "10:06", "sender": "렌터카 상담 박매니저", "message": "해당 차량 견적입니다."},
      {"time": "10:10", "sender": "렌터카 상담 박매니저", "message": "통화 가능하실까요?"}]),
    ("KB캐피탈 X 차살때 김범중", "네 알겠습니다 주말이라 새로운 재고가 업로드가 안되어서 월요일에 출근해서 새로 올라오는 재고 확인 후에 연락드리겠습니다", None),
    ("헬로장기렌트", "팀장님 좋은 견적 다시 준비해서 보내드리겠습니다. 조금만 기다려주세요.", None),
    ("이수만 보험설계사", "고객님 검토 후에 다시 연락드리겠습니다. 좋은 하루 되세요!", None),
    ("부동산 김실장", "매물 사진 몇 장 더 보내드리겠습니다. 확인해보시고 말씀주세요.", None),
    ("차량 매니저 윤소희", "네 확인하고 다시 연락드릴게요. 진행 결정되시면 말씀 주세요.", None),
    ("인테리어 박소장", "견적서 정리해서 내일 중으로 보내드리겠습니다.", None),
    ("KB캐피탈 X 차살때 김범중", "한번 더 검토해서 좋은 조건 드릴 수 있는지 말씀드리겠습니다 :-)", None),
    ("정수기 렌탈 상담원", "상담 도와드린 내용 정리해서 문자로 보내드릴게요. 편하실 때 보세요.", None),
    ("여행사 이대리", "항공권 옵션 몇 개 비교해서 메일로 정리해드리겠습니다.", None),
]
for i, (snd, msg, th) in enumerate(B):
    rows.append(neg(f"r34_logi_{i:02d}", RECV, snd, msg, thread=th))

# ── C. 인사말/안부 음성 ───────────────────────────────────────────────────────
C = [
    ("렌탈센터 정실장", "안녕하세요. 행복렌탈 정실장입니다.\n월요일 아침이 밝았습니다. 이번 한 주도 건강하시고 하시는 모든 일 잘 되시길 바랍니다. 활기찬 한 주 되세요. 감사합니다."),
    ("김부장", "주말 잘 보내셨어요? 이번 주도 화이팅입니다!"),
    ("이모", "우리 조카 잘 지내지? 밥 잘 챙겨먹고 다녀~ 보고싶다 ㅎㅎ"),
    ("동창 민수", "오랜만이다! 잘 지내냐? 조만간 얼굴 한번 보자~"),
    ("거래처 최부장", "추석 명절 잘 보내시고 가정에 항상 행복이 가득하시길 바랍니다."),
    ("선배", "고생 많았어. 푹 쉬고 다음에 또 보자."),
    ("스퀘어네트 송은정", "교수님 오늘도 좋은 하루 보내세요! 항상 감사드립니다."),
    ("할머니", "아이고 우리 강아지 추운데 옷 따뜻하게 입고 다녀라"),
]
for i, (snd, msg) in enumerate(C):
    rows.append(neg(f"r34_greet_{i:02d}", RECV, snd, msg))

# ── D. 긴 행사명 무시간/무장소 양성 (time:null·location:null — 환각·제목복제 억제) ──
D_POS = [
    ("대구테크노파크 선정기업 통합간담회", "화요일", "정규민 교수", "화요일에 대구테크노파크 선정기업 통합간담회 참석합니다."),
    ("창업진흥원 스타트업 원스톱 지원센터 설명회", "내일", "창업진흥원", "내일 창업진흥원 스타트업 원스톱 지원센터 설명회가 있습니다."),
    ("모두의 창업 1기 중간 점검 멘토링", "다음주월", "변수룡 멘토", "다음주 월요일 모두의 창업 1기 중간 점검 멘토링 진행합니다."),
    ("전문개인투자자 양성 교육과정 수료식", "금요일", "엔젤투자허브", "금요일에 전문개인투자자 양성 교육과정 수료식이 예정되어 있습니다."),
    ("지역 스타트업 IR 데모데이", "다음주수", "창경센터", "다음주 수요일 지역 스타트업 IR 데모데이 참석 예정입니다."),
    ("AI 부트캠프 오리엔테이션", "모레", "스퀘어네트", "모레 AI 부트캠프 오리엔테이션 있습니다."),
]
for i, (title, d, snd, msg) in enumerate(D_POS):
    rows.append(pos(f"r34_longev_{i:02d}", RECV, snd, msg,
                    [ev(title, d, None, location=None, all_day=False, conf=0.8)]))

# ── E. 지나가는 행사 언급 음성 (내 일정 아님 / 행사 단순 언급) ──────────────────
E = [
    ("정규민 교수", "내일 종일 간담회가 있어서 좀 정신없을 것 같아요. 연락이 늦어도 이해해주세요."),
    ("김현민", "이번 주는 워크숍 준비 때문에 많이 바쁘네요 ㅠㅠ"),
    ("송은정", "어제 세미나 잘 마쳤습니다. 참석해주신 분들께 감사드려요."),
    ("변수룡 교수", "지난번 행사 사진 정리되면 공유드릴게요."),
    ("박과장", "다음 분기에 큰 행사가 하나 있을 것 같은데 아직 일정은 미정이에요."),
]
for i, (snd, msg) in enumerate(E):
    rows.append(neg(f"r34_mention_{i:02d}", RECV, snd, msg))

# ── 검증 ──────────────────────────────────────────────────────────────────────
bad = 0
for r in rows:
    for e in r["gold"]["events"]:
        res = resolve_when(r["received_at"], e["date"], e["time"], e["end_time"], e["all_day"])
        if e["date"] and res["start"] is None:
            bad += 1
            print("  ! resolve 실패:", r["scenario_id"], repr(e["date"]))

npos = sum(1 for r in rows if r["gold"]["has_schedule"])
nneg = len(rows) - npos
print(f"생성 {len(rows)}행: 양성 {npos} · 음성 {nneg} | resolve 실패 {bad}")
print(f"  음성 내역 — 서비스알림 {len(A)} · 로지스틱스 {len(B)} · 인사말 {len(C)} · 지나가는언급 {len(E)}")
print(f"  양성 — 긴행사명 무시간/무장소 {len(D_POS)}")
out = Path("data/processed/_r34_add.jsonl")
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"→ {out}")
