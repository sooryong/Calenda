"""실제 SMS(adb로 수집) → 학습/평가 데이터셋 빌더.

발신자=본인번호인 '자기 일정 메모'가 양성, 재난문자/OTP/광고/거래알림이 음성.
received_at은 SMS의 epoch(ms)를 KST로 변환. 상대 날짜는 토큰(내일/모레/이번주화…),
명시 날짜는 YYYY-MM-DD. 출력: data/processed/sms_real.jsonl(학습) + data/eval/sms_real.jsonl(골든).
"""
import json
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def pos(title, date, time=None, end_time=None, all_day=False, location=None,
        attendees=None, organizer=None, description=None, conf=0.85):
    return {"has_schedule": True, "events": [{
        "title": title, "date": date, "time": time, "end_time": end_time,
        "all_day": all_day, "location": location, "attendees": attendees or [],
        "organizer": organizer, "description": description, "recurrence": None,
        "confidence": conf}]}


NEG = {"has_schedule": False, "events": []}
SELF = "01038139885"

# (epoch_ms, sender, message, gold, split, language)
ROWS = [
    # ── 양성: 자기 일정 메모 ──
    (1779642386377, SELF, "30일 오후1시 미드포인트", pos("미드포인트", "2026-05-30", {"hour": 1, "minute": 0, "marker": "오후"}), "golden", "ko"),
    (1779641700554, SELF, "5월 26일 종소세 신고", pos("종합소득세 신고", "2026-05-26", None, all_day=True, conf=0.8), "golden", "ko"),
    (1779641548724, SELF, "5.30 12시부터 코6 미드포인트", pos("코6 미드포인트", "2026-05-30", {"hour": 12, "minute": 0, "marker": None}), "train", "ko"),
    (1779641507893, SELF, "5.29 13시 경북대 심사", pos("경북대 심사", "2026-05-29", {"hour": 13, "minute": 0, "marker": None}, location="경북대"), "golden", "ko"),
    (1779641254984, SELF, "5웚28일 13시부터 경북대 심사", pos("경북대 심사", "2026-05-28", {"hour": 13, "minute": 0, "marker": None}, location="경북대"), "train", "ko"),
    (1779640720308, SELF, "5월 25일 09시 30분 감포 출발", pos("감포 출발", "2026-05-25", {"hour": 9, "minute": 30, "marker": None}), "golden", "ko"),
    (1778381231290, SELF, "내일 10시 양승모 대표에게 전화, 010-3129-6924", pos("양승모 대표 전화", "내일", {"hour": 10, "minute": 0, "marker": None}, attendees=["양승모 대표"], description="010-3129-6924"), "train", "ko"),
    (1777984464871, SELF, "내일 14시 화성행 버스 예약", pos("화성행 버스", "내일", {"hour": 14, "minute": 0, "marker": None}), "golden", "ko"),
    (1777984350246, SELF, "수요일 11시 화성 기차예약", pos("화성 기차", "이번주수", {"hour": 11, "minute": 0, "marker": None}, conf=0.8), "train", "ko"),
    (1777981686802, SELF, "이번 목요일 19시 화성행 버스예약", pos("화성행 버스", "이번주목", {"hour": 19, "minute": 0, "marker": None}), "golden", "ko"),
    (1777808023531, SELF, "이번 화요일 15시 심교수 미팅", pos("심교수 미팅", "이번주화", {"hour": 15, "minute": 0, "marker": None}, attendees=["심교수"]), "train", "ko"),
    (1777804189011, SELF, "내일 15시에 헬스장 등록하기", pos("헬스장 등록", "내일", {"hour": 15, "minute": 0, "marker": None}, conf=0.82), "golden", "ko"),
    (1777803755062, SELF, "5월5일 저녁식사 예약 17시30분", pos("저녁식사", "2026-05-05", {"hour": 17, "minute": 30, "marker": None}), "train", "ko"),
    (1777780988090, SELF, "5/5 13시 신천에서 운동", pos("운동", "2026-05-05", {"hour": 13, "minute": 0, "marker": None}, location="신천"), "golden", "ko"),
    (1777776751946, SELF, "모레 12시 운동", pos("운동", "모레", {"hour": 12, "minute": 0, "marker": None}, conf=0.82), "train", "ko"),
    (1777754486218, SELF, "13일 12시부터 14시까지 경북대 스타트업 허브에서 서류 심사", pos("서류 심사", "2026-05-13", {"hour": 12, "minute": 0, "marker": None}, end_time={"hour": 14, "minute": 0, "marker": None}, location="경북대 스타트업 허브"), "train", "ko"),
    # ── 음성: 재난문자/OTP/광고/거래/잡담 ──
    (1780268933169, "#CMAS#Amber", "북구에서 실종된 정운학씨(남,69세)를 찾습니다. 173cm,57kg,백발상고,베이지체크반팔,청바지,운동화,선글라스 vo.la/T1IDT /☎112 [대구경찰청]", NEG, "golden", "ko"),
    (1780013322850, "16666805", "[Web발신]\n[금융결제원] 확인코드(2자리)를 문자로 답장한 후 서비스 화면으로 돌아가세요.", NEG, "train", "ko"),
    (1779878222455, "+17637032142", "[국외발신]\nYour Kaggle verification code is: 1507", NEG, "golden", "mixed_ko_en"),
    (1779845269117, "01031444253", "[Web발신]\n(광고) 대구cc 최고가 매도/매수가능 기타회원권문의가능 무료수신거부 0808804936", NEG, "train", "ko"),
    (1779777937665, "#CMAS#Severe", "서울-신촌 간 서소문 고가 도로 철거 공사 중 붕괴로 열차 운행 중지 등 상당한 차질이 발생하고 있으니 타 교통 수단을 이용하여 주시기 바랍니다[한국철도공사]", NEG, "train", "ko"),
    (1779674220801, "15993333", "[Web발신]\n[카카오뱅크] 카드결제실패\n변*룡(0304)\n05/25 10:56\n100,000원\n서라벌셀프주유소\n잔액부족", NEG, "golden", "ko"),
    (1779667054591, "027081007", "[Web발신]\n<#>[인증번호:658329] - 카카오페이\n(타인노출금지)", NEG, "train", "ko"),
    (1779621700773, "15882114", "[Web발신]\n[현대캐피탈 본인확인] 인증번호[575177]을 입력해 주세요.", NEG, "train", "ko"),
    (1779327938902, "01058018471", "[Web발신]\n(광고) 소노호텔&리조트 각 분양가별 최저가 매수가능 급매물! 무료수신거부 0808804934", NEG, "golden", "ko"),
    (1779107300184, "01081790809", "곧 연락드리겠습니다.", NEG, "train", "ko"),
    (1778648649904, "0535854224", "[Web발신]\n(광고)자이언트골프 대구출장가게 골프+관광 6/7 단하루특가 올포함 89.9만~ 무료거부0808554224", NEG, "train", "ko"),
    (1778473705600, "#CMAS#Severe", "오늘 13:06 대구시 동구 도학동 산10-1 산불 발생. 입산 금지. 인근 주민과 등산객은 안전사고에 주의하세요. [대구광역시]", NEG, "golden", "ko"),
    (1778335815421, "01090073909", "디브리핑 거의 마무리 되고 있음", NEG, "train", "ko"),
    (1778107618438, "#CMAS#Severe", "금일 07시 트레일러 관련 사고 발생으로 경부고속도로 서울방향 149.1km 칠곡물류부근 1,2차로 통제되어 극심한 정체중이오니 국도우회바랍니다. [한국도로공사]", NEG, "train", "ko"),
    (1778021059032, "15446633", "[Web발신]\n[STELLA]로그인 인증번호는 0249646 입니다. 인증번호를 정확히 입력하세요.", NEG, "train", "ko"),
    (1777714492950, "15997052", "[Web발신]\n내정보지키미 이달의 쿠폰\n앱에서 즉시 확인 ▶ https://safemyinfo.kr/app_install", NEG, "golden", "ko"),
    (1777686509661, "0220338500", "[Web발신]\n[한국모바일인증(주)]본인확인 인증번호[256931]입니다. \"타인 노출 금지\"", NEG, "train", "ko"),
    (1779599950057, "0220338500", "[Web발신]\n[KT] 인증번호: 990575 본인 확인을 위해 입력해 주세요.", NEG, "golden", "ko"),
    (1777601775612, "#CMAS#Severe", "건조주의보 지속발효 중. 산림인접지 절대소각금지, 입산시 화기소지금지(위반시 과태료 최대200만원)[대구광역시]", NEG, "train", "ko"),
    (1779714360429, "#CMAS#Severe", "안전사고(낙석) 예방을 위해 2026. 5. 26.(화) 00시 부로 신천대로 하단도로 일부(수성중학교→상동교) 통제하오니 우회하시기 바랍니다. [대구광역시]", NEG, "train", "ko"),
]


def main():
    train, golden = [], []
    for i, (ep, sender, msg, gold, split, lang) in enumerate(ROWS):
        rec = {
            "scenario_id": f"sms_real_{i:03d}",
            "received_at": datetime.fromtimestamp(ep / 1000, KST).isoformat(),
            "channel": "sms", "sender": sender, "language": lang,
            "message": msg, "gold": gold,
        }
        (golden if split == "golden" else train).append(rec)
    for path, rows in [("data/processed/sms_real.jsonl", train), ("data/eval/sms_real.jsonl", golden)]:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        p = sum(1 for r in rows if r["gold"]["has_schedule"])
        print(f"{path}: {len(rows)}건 (일정 {p} / 음성 {len(rows) - p})")


if __name__ == "__main__":
    main()
