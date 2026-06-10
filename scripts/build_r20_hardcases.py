"""r20 하드케이스 빌더 — 실사용 2대 실패 교정.

실패(2026-06-10 실캡처):
  ① 과발화: "출금 6,000원 · 카카오뱅크"(가맹점=경북대학교생활협동조합)가 93%로 등록.
     기존 거래알림 음성(ad_negative)은 '입출금통장(7897)→이름' 계좌포맷뿐 → 가맹점이 **장소처럼 생긴**
     카드결제(승인/출금 + 금액 + 기관/매장명)를 못 거름. 모델이 [장소+날짜+시각] 3박자로 일정 키잉.
  ② 미탐: 격식 기관메일(대구창조경제혁신센터 멘토링)에서 "6월 16일(화) … 출범식" 미검출.
     진짜 원인은 Gmail 알림 미리보기 잘림(본문 3문단째)이라 데이터로는 그 메일 자체는 못 고치나,
     **풀바디가 들어왔을 때** 격식·장문·'참석 필수 아님' 헤지 표현 속 묻힌 일정을 양성으로 잡게 학습.

그룹:
  G1 가맹점-장소형 카드결제/거래알림 음성 — sender=은행/카드/페이, 승인/출금/결제 + 금액 + 매장(장소형) → false.
  G2 격식 기관메일 선택적-참석 양성 — 장문·헤지('참석 필수 아님'·'가능 시 회신')라도 확정 일자 행사면 true.
  G3 격식 기관메일 음성 — 자료송부·회신요청·'추후 안내'(확정일자 없음) → false (G2 과발화 방지).

월-일은 표면형 토큰('7월3일'·'6/24')로 gold 기록 — resolver가 가까운 미래로 변환(연도 산술 0.5B 회피).
출력: data/processed/r20_hardcases.jsonl
사용: python scripts/build_r20_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

RECV_BASE = "2026-06-10"


def ev(title, date, *, time=None, all_day=False, attendees=None, organizer=None,
       location=None, description=None, confidence=0.9):
    return {"title": title, "date": date, "time": time, "end_time": None, "all_day": all_day,
            "location": location, "attendees": attendees or [], "organizer": organizer,
            "description": description, "recurrence": None, "confidence": confidence}


def T(h, m=0, marker=None):
    return {"hour": h, "minute": m, "marker": marker}


# ── G1: 가맹점-장소형 카드결제/거래알림 음성 (has_schedule:false) ───────────────
# 핵심: 발신=은행/카드/페이 브랜드 + 승인/출금/결제/이체 + 금액(원) + **장소처럼 생긴 가맹점**.
# 날짜·시각·장소가 다 있어 신뢰도가 높게 오르지만 전부 음성. 계좌포맷·매장포맷 모두 포함.
TXN_NEG = [
    ("kakao", "카카오뱅크", "출금 14,300원\n경북대학교 생협 매점\n06/08 12:47\n잔액 412,300원"),
    ("kakao", "카카오뱅크", "체크카드 승인\n4,500원 일시불\n06/11 08:14\n스타벅스 동대구역점\n잔액 405,800원"),
    ("kakao", "카카오뱅크", "출금 12,000원\n경북대병원 주차장\n06/09 18:42\n잔액 388,000원"),
    ("sms", "신한카드", "[신한카드] 승인 김수룡\n7,900원 일시불\n06/12 12:33\nGS25 경대북문점"),
    ("sms", "삼성카드", "[삼성카드] 박정우님\n23,000원 승인\n06/13 19:05\n이마트 칠곡점\n할부 일시불"),
    ("kakao", "토스", "결제 완료\n06/10 13:20\n메가커피 산격점\n2,000원\n잔액 88,400원"),
    ("kakao", "국민은행", "[KB] 체크카드 출금\n9,800원\n06/14 21:11\n맘스터치 경대점\n계좌(9012)"),
    ("sms", "현대카드", "[현대카드] 승인\n55,000원 3개월\n06/15 17:48\n경북대학교 글로벌플라자 매점"),
    ("kakao", "카카오페이", "결제 1,500원\n06/10 09:02\n경북대 도서관 매점\n포인트 적립 15P"),
    ("sms", "롯데카드", "[롯데카드] 승인 12,400원\n06/16 20:30\n파리바게뜨 복현점\n홍길동님"),
    ("kakao", "신한은행", "[신한] 출금 30,000원\n06/18 14:00\n대구은행연수원 식당\n신한주거래(1234)"),
    ("sms", "우리카드", "[우리카드] 승인\n8,000원 일시불\n06/17 11:25\n투썸플레이스 경북대점"),
    ("kakao", "토스", "결제 완료\n06/19 18:55\n쿠우쿠우 대구점\n34,000원\n잔액 51,200원"),
    ("kakao", "카카오뱅크", "입금 50,000원\n06/20 09:12\n입출금통장(7897) ← 김민수\n잔액 462,300원"),
    ("sms", "하나카드", "[하나카드] 06/21 13:40 승인\n6,800원\n컴포즈커피 경대점\n일시불"),
    ("kakao", "NH농협은행", "[NH농협] CMS 출금 89,000원\n06/22 06:30\n경북대학교 기숙사 관리비\n농협(4321)"),
    ("sms", "BC카드", "[BC카드] 승인 41,200원\n06/23 19:18\n홈플러스 내당점\n2개월 할부"),
    ("kakao", "케이뱅크", "체크카드 결제\n3,300원\n06/24 08:40\n이디야커피 경북대북문점\n잔액 77,100원"),
    ("sms", "신한카드", "[신한카드] 해외승인\nUSD 9.99\n06/25 03:14\nGOOGLE *YOUTUBE\n약 13,700원"),
    ("kakao", "카카오뱅크", "자동이체 출금 600,000원\n06/25 10:00\n경북대학교 등록금\n잔액 102,300원"),
]

# ── G2: 격식 기관메일 — 선택적 참석 + 확정 일자 행사 (has_schedule:true) ────────
# 장문·격식·'참석 필수 아님/가능 시 회신' 헤지 속에 **확정 일자 행사**가 있으면 양성.
# title=행사 활동명(출범식/발대식/오리엔테이션/간담회/세미나/워크숍/착수보고회/네트워킹데이).
GOV_POS = [
    ("gmail", "startup@dgist.ac.kr",
     "안녕하십니까. DGIST 창업지원단입니다. 관련 자료 송부드리니 첨부 참고 부탁드립니다. 또한 7월 3일(목) 대구 엑스코에서 진행되는 「청년창업」 발대식을 안내드립니다. 참석이 필수 사항은 아니나 참석 시 멘토 소개가 진행되며, 가능하신 경우 회신 부탁드립니다.",
     ev("발대식", "7월3일", all_day=True, location="대구 엑스코", confidence=0.85)),
    ("gmail", "freedaegu@naver.com",
     "안녕하세요 멘토님. 예비창업팀입니다. 안내문 함께 전달드리오니 참고 부탁드립니다. 6월 24일(수) 오후 2시 경북대학교 IT융복합관에서 멘토·멘티 네트워킹데이가 예정되어 있습니다. 멘토님 참석이 의무는 아니지만 참석 가능하시면 함께 자리해 주시면 감사하겠습니다.",
     ev("네트워킹데이", "6월24일", time=T(2, marker="오후"), location="경북대학교 IT융복합관", confidence=0.85)),
    ("gmail", "support@kised.or.kr",
     "창업진흥원입니다. 사업 관련 안내드립니다. 7월 8일(화) 오전 10시 서울 코엑스 컨퍼런스룸에서 사업설명회를 개최하오니 관심 있으신 분들의 많은 참여 부탁드립니다. 사전등록은 회신으로 가능합니다.",
     ev("사업설명회", "7월8일", time=T(10, marker="오전"), location="서울 코엑스 컨퍼런스룸", confidence=0.9)),
    ("gmail", "office@knu.ac.kr",
     "경북대학교 산학협력단입니다. 첨부 자료 검토 부탁드립니다. 아울러 6월 27일(금) 오후 4시 글로벌플라자 2층에서 협약식이 진행될 예정입니다. 일정상 어려우시면 참석하지 않으셔도 무방하나 가급적 참석 부탁드립니다.",
     ev("협약식", "6월27일", time=T(4, marker="오후"), location="글로벌플라자 2층", confidence=0.85)),
    ("gmail", "admin@ccei.kr",
     "안녕하세요. 창조경제혁신센터입니다. 멘토링 운영 관련 안내드립니다. 7월 15일(수) 종일 일정으로 워크숍을 진행합니다. 장소는 대구 인터불고호텔이며, 참석 여부를 7월 5일까지 회신 부탁드립니다.",
     ev("워크숍", "7월15일", all_day=True, location="대구 인터불고호텔", confidence=0.85)),
    ("gmail", "pm@tips.or.kr",
     "TIPS 운영사입니다. 협약 체결 관련 안내드립니다. 6월 30일(월) 오후 3시 착수보고회를 진행하오니 참석 부탁드립니다. 부득이 참석이 어려우시면 사전에 알려주시기 바랍니다.",
     ev("착수보고회", "6월30일", time=T(3, marker="오후"), confidence=0.85)),
    ("gmail", "edu@daegu.go.kr",
     "대구광역시 일자리노동정책과입니다. 안내문 송부드립니다. 7월 2일(수) 오전 11시 대구시청 별관 대강당에서 오리엔테이션이 예정되어 있습니다. 참석이 필수는 아니나 가급적 참석 권장드립니다.",
     ev("오리엔테이션", "7월2일", time=T(11, marker="오전"), location="대구시청 별관 대강당", confidence=0.85)),
    ("gmail", "secretary@academy.or.kr",
     "안녕하십니까. 한국멘토아카데미 사무국입니다. 자료 전달드립니다. 더불어 7월 10일(목) 저녁 7시 동대구 그랜드호텔에서 멘토 간담회를 개최합니다. 참석 가능 여부 회신 부탁드립니다.",
     ev("간담회", "7월10일", time=T(7, marker="저녁"), location="동대구 그랜드호텔", confidence=0.85)),
    ("gmail", "info@startupbiz.kr",
     "스타트업비즈 사무국입니다. 안내드립니다. 6월 26일(금) 오후 1시 30분 경북대학교 첨성관에서 데모데이를 진행합니다. 멘토님들의 참관은 자율이오나 참석 시 미리 회신 주시면 좌석을 준비하겠습니다.",
     ev("데모데이", "6월26일", time=T(1, m=30, marker="오후"), location="경북대학교 첨성관", confidence=0.85)),
    ("gmail", "host@founders.kr",
     "파운더스포럼 운영팀입니다. 첨부 안내문 참고 바랍니다. 7월 22일(화) 종일 부산 벡스코에서 창업 네트워킹 행사가 열립니다. 참석은 선택이며 관심 있으신 경우 회신 부탁드립니다.",
     ev("창업 네트워킹 행사", "7월22일", all_day=True, location="부산 벡스코", confidence=0.8)),
    ("gmail", "office@univ-startup.ac.kr",
     "산학협력중점교수 협의회입니다. 자료 공유드립니다. 아울러 6월 29일(월) 오전 9시 30분 본관 세미나실에서 정기 세미나가 있습니다. 바쁘시면 불참하셔도 되나 가능하면 참석 부탁드립니다.",
     ev("정기 세미나", "6월29일", time=T(9, m=30, marker="오전"), location="본관 세미나실", confidence=0.85)),
    ("gmail", "manager@incubator.kr",
     "창업보육센터입니다. 운영 안내드립니다. 7월 4일(금) 오후 5시 입주기업 간담회를 진행할 예정입니다. 참석이 의무는 아니지만 입주사 대표님들의 많은 참석 바랍니다.",
     ev("입주기업 간담회", "7월4일", time=T(5, marker="오후"), confidence=0.85)),
]

# ── G3: 격식 기관메일 음성 — 확정 일자 행사 없음 (has_schedule:false) ───────────
# 격식·기관 발신이라도 '자료 송부/검토 요청/추후 안내/지난 행사'면 음성. G2 과발화 차단.
GOV_NEG = [
    ("gmail", "freedaegu@naver.com", "안녕하세요 멘토님. 책임멘토 멘토링 안내문과 집행가이드를 송부드리니 첨부파일 참고 부탁드립니다. 문의사항 있으시면 언제든 연락 부탁드립니다."),
    ("gmail", "support@kised.or.kr", "창업진흥원입니다. 온라인·오프라인 멘토링 멘토비 지급 기준은 추후 별도 안내 예정입니다. 세부 기준 확정 시 다시 전달드리겠습니다."),
    ("gmail", "office@knu.ac.kr", "경북대 산학협력단입니다. 협약서 양식과 제출 서류 목록을 첨부합니다. 검토 후 회신 부탁드립니다. 마감일은 추후 공지하겠습니다."),
    ("gmail", "admin@ccei.kr", "창조경제혁신센터입니다. 지난 출범식 사진과 행사 후기를 공유드립니다. 참석해 주신 멘토님들께 감사드립니다."),
    ("gmail", "edu@daegu.go.kr", "대구시 일자리노동정책과입니다. 사업 공고문과 신청 양식을 안내드립니다. 자세한 일정은 확정되는 대로 다시 안내드리겠습니다."),
    ("gmail", "pm@tips.or.kr", "TIPS 운영사입니다. 협약 관련 제출 서류를 안내드립니다. 착수보고회 일정은 협약 완료 후 별도 조율 예정입니다."),
    ("gmail", "secretary@academy.or.kr", "멘토아카데미 사무국입니다. 멘토 활동비 정산 양식을 첨부하오니 작성하여 회신 부탁드립니다."),
    ("gmail", "info@startupbiz.kr", "스타트업비즈입니다. 멘토 프로필 등록을 부탁드립니다. 데모데이 일정은 참가사 확정 후 안내드리겠습니다."),
]


def pos_rows(records, prefix):
    out = []
    for i, (ch, sender, msg, e) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{8 + (i % 12):02d}:{(i * 7) % 60:02d}:00+09:00",
                    "channel": ch, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": True, "events": [e]}})
    return out


def neg_rows(records, prefix):
    out = []
    for i, (ch, sender, msg) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{9 + (i % 12):02d}:{(i * 13) % 60:02d}:00+09:00",
                    "channel": ch, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": False, "events": []}})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    groups = {
        "G1 가맹점-장소형 거래알림 음성": neg_rows(TXN_NEG, "g20_txn"),
        "G2 격식 기관메일 선택참석 양성": pos_rows(GOV_POS, "g20_gov"),
        "G3 격식 기관메일 음성": neg_rows(GOV_NEG, "g20_govneg"),
    }
    rows = [r for g in groups.values() for r in g]
    pos = sum(1 for r in rows if r["gold"]["has_schedule"])
    neg = len(rows) - pos
    for name, g in groups.items():
        gp = sum(1 for r in g if r["gold"]["has_schedule"])
        print(f"  {name:26} {len(g):3}  (양성 {gp}, 음성 {len(g)-gp})")
    print(f"  {'합계':26} {len(rows):3}  (양성 {pos} / 음성 {neg}, 음성 {neg/len(rows):.0%})")
    if args.apply:
        p = "data/processed/r20_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
