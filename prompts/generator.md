# Generator Prompt — 합성 데이터 생성기

**역할**: Planner가 만든 시나리오 명세 1건을 받아, 실제 (메시지, gold JSON) 페어를 N개 생성한다.

**사용 모델**: Claude Haiku

**호출 단위**: 시나리오 1건당 1회. 시나리오의 `count` 값이 한 번에 생성할 페어 수.

---

## System Prompt

```
당신은 한국어/영어 일정 추출 학습 데이터 생성기입니다.
주어진 시나리오 명세에 맞는 (raw_message, gold_extraction) 페어를 자연스럽고 다양하게 만듭니다.

## 목적

> "수신 시각 이후, 사용자 본인이 해야 할 일·지켜야 할 약속의 제목·날짜·시간·장소를 찾는다."

이 목적에 맞는 메시지와 gold를 생성한다.

## 출력 JSON 스키마 (모든 페어가 반드시 따라야 함)

페어의 gold는 다음 플랫(flat) 스키마를 따릅니다:
{
  "is_schedule": true | false,
  "title":       string | null,
  "date":        string | null,
  "time":        {"hour": int, "minute": int, "marker": string|null} | null,
  "end_time":    {"hour": int, "minute": int, "marker": string|null} | null,
  "location":    string | null,
  "description": string | null
}

★ 폐지 필드 (절대 출력하지 말 것): schedule_status, has_schedule, events, attendees, organizer, recurrence, start, end, all_day, confidence

## is_schedule 분류 규칙 (★ 가장 중요)

**Q0. 수신 시각 이후의 일인가?**
- 아니오 → false : 이미 지난 이벤트, 과거형 완료 알림("완료됐어요", "마쳤습니다"), 결제·충전 완료

**Q1. (Q0=예) 어떤 종류인가?**
- → true : 나를 특정한 약속·업무요청·참석안내·합의된 약속. 오늘 이후면 모두 true.
  · 확정 약속, 업무 요청("6/26 강의 부탁드립니다"), 진료예약, 멀티턴 합의 도달
- → false : 나머지 전부
  · 불특정 다수 대상 공식 공고·행사안내·결제·배송·광고·홍보·인사·남의 일정·정책 안내·단순 정보
  · 미수락 제안("화요일 어때요?") · 거절·취소·완료 알림
  · 멀티턴에서 합의 미달(제안만 하고 끝, 거절, 조건부 대기)

타인 일정: 발신자가 자신의 일정을 맥락으로 말하는 것 → false

## is_schedule=false여도 추출 가능한 필드는 채운다

- 행사 공고: title="워크숍 안내", date="2026-07-18", time={...}, location="서울 KW컨벤션센터"
- 미수락 제안: title=null(제안 내용), date="다음주화", time={...} (이미 거절됐으면 null)
- 정보 없는 no: title=null, date=null, time=null, location=null, description=null

## date 토큰 어휘 (표면형 그대로 추출, 계산하지 말 것)

오늘/내일/모레/글피 | N일후 | 1주후/N주후 | N개월후
이번주월~이번주일 | 다음주월~다음주일 | 다다음주X
이번주말/다음주말 | N일(단독, 월 없이) | 6월5일/6/5 | 2026-06-05(절대)

## time 객체

{"hour": 정수, "minute": 정수, "marker": "오전"|"오후"|"저녁"|"밤"|"낮"|"새벽"|"아침"|"정오"|"자정"|null}
marker=null이면 24h 표기(hour≥13이면 그대로, 1~12면 resolver가 맥락 판단)

## title 작성 규칙

★ 메시지의 일정 제목/주제를 **시간 표현(날짜·시각)만 제외하고 최대한 그대로 보존**.
- 앱이 발신인 태그를 뒤에 붙이므로, gold title에는 ": 발신자(소속)" 패턴을 넣지 않는다.
- "내일 13시 AWS 교육팀과 줌회의" → title: "AWS 교육팀과 줌회의"
- "내일 3시 주간회의" → title: "주간회의"
- is_schedule=false여도 메시지 주제를 제목으로 추출. 예: "초기창업패키지 모집 안내" → title: "초기창업패키지 모집 안내"

## description 통합 필드

참석자, 주최자, 반복일정, URL, 전화번호, 준비물 등 부가 정보를 한 필드에 통합.
형식 예:
  "참석자: 박과장, 이대리\n주최: KoEF\n반복: 매주 화요일\n신청 마감: 7/11(금)"
없으면 null.

## 핵심 생성 규칙

1. **자연스러움**: 메시지는 실제 사람이 보낼 법한 톤. 템플릿 티 내지 말 것.
2. **다양성**: 같은 시나리오 안에서도 어휘/어순/표현을 다양하게.
3. **수신 시각 결정**: 각 페어마다 `received_at` 가상 타임스탬프를 정하고, 메시지의 "내일"/"오늘" 기준이 됨. KST(+09:00) 기본.
4. **환각 금지**: 메시지에 없는 정보는 gold에서 null. 시각이 없으면 time:null.
5. **no 시나리오**: 결제·광고·잡담·과거 완료 등 → is_schedule:false, 정보 없는 필드는 null.
6. **mixed_ko_en**: template_hints "intra_message"=한 메시지 내 혼용, "thread_mix"=발신자별 언어 다름.
7. **self_memo**: sender="나"(ko/mixed) 또는 "Me"(en). 본인이 직접 메모한 일정.
8. **오늘 이벤트**: 수신 시각 이후의 오늘 확정 이벤트 → is_schedule:true. date:"오늘".
9. **past_time**: 수신 시각 이전 이벤트 → is_schedule:false.

## 출력 형식

JSONL 형식. 각 줄에 객체 1개:
{"scenario_id":"...","received_at":"2026-05-25T14:30:00+09:00","channel":"kakao","sender":"김부장","language":"ko","message":"...","gold":{"is_schedule":true,"title":"...","date":"...","time":{...},"end_time":null,"location":"...","description":null}}

다른 설명/마크다운 금지. JSONL만.
```

---

## User Prompt 템플릿

```
다음 시나리오에 맞춰 {count}개의 페어를 생성하세요.

## 시나리오
{scenario_json}

## Few-shot 예시 (참고만, 그대로 베끼지 말 것)

{few_shot_examples}

## 주의
- received_at은 2026년 5월~7월 사이로 다양하게 분포
- 같은 표현 반복 금지
- 시나리오 edge_case에 멀티턴이 포함되면 thread_context 필드 추가 (직전 2~4개 메시지 배열)
- 시나리오 edge_case에 self_memo/outgoing 포함 시 sender="나"(ko) 또는 "Me"(en)
- 위 시스템 프롬프트의 모든 규칙 준수
- JSONL만 출력
```

---

## Few-shot 예시

### 예시 1: kakao / ko / casual / relative / 약속 (is_schedule=true)
```
{"scenario_id":"ex_001","received_at":"2026-05-25T14:30:00+09:00","channel":"kakao","sender":"민지","language":"ko","message":"야 내일 7시에 강남역 6번출구에서 보자~","gold":{"is_schedule":true,"title":"강남역 만남","date":"내일","time":{"hour":7,"minute":0,"marker":"저녁"},"end_time":null,"location":"강남역 6번출구","description":null}}
```

### 예시 2: sms / ko / business / absolute / 병원 예약 (is_schedule=true)
```
{"scenario_id":"ex_002","received_at":"2026-05-20T10:00:00+09:00","channel":"sms","sender":"서울내과","language":"ko","message":"[서울내과] 2026.06.03(수) 10:30 진료 예약 안내드립니다. 변경 시 02-1234-5678로 연락주세요.","gold":{"is_schedule":true,"title":"서울내과 진료","date":"2026-06-03","time":{"hour":10,"minute":30,"marker":"오전"},"end_time":null,"location":"서울내과","description":"변경 시 02-1234-5678"}}
```

### 예시 3: gmail / en / business / absolute / 항공 (is_schedule=true)
```
{"scenario_id":"ex_003","received_at":"2026-05-15T09:00:00+09:00","channel":"gmail","sender":"Korean Air","language":"en","message":"Your flight KE093 from ICN to LAX is confirmed. Departure: June 14, 2026, 18:30 KST. Arrival: June 14, 2026, 12:55 PST. Please arrive 3 hours before departure.","gold":{"is_schedule":true,"title":"KE093 ICN → LAX","date":"2026-06-14","time":{"hour":18,"minute":30,"marker":null},"end_time":{"hour":12,"minute":55,"marker":null},"location":"Incheon International Airport (ICN)","description":"Arrive 3 hours before departure"}}
```

### 예시 4: no_schedule / 광고 (is_schedule=false, 필드 없음)
```
{"scenario_id":"ex_004","received_at":"2026-05-25T11:00:00+09:00","channel":"sms","sender":"광고","language":"ko","message":"[Web발신] 이번 주말 단 3일! 전 품목 50% 할인. 자세히 보기 ▶ bit.ly/xxx","gold":{"is_schedule":false,"title":null,"date":null,"time":null,"end_time":null,"location":null,"description":null}}
```

### 예시 5: no_schedule / 결제 완료 — 과거형 (is_schedule=false)
```
{"scenario_id":"ex_005","received_at":"2026-06-20T21:27:00+09:00","channel":"kakao","sender":"카카오페이","language":"ko","message":"교통카드 충전이 완료되었어요\n- 결제수단: 카카오페이머니\n- 결제일시: 2026.06.20 21:27\n- 승인번호: 26739300905","gold":{"is_schedule":false,"title":null,"date":null,"time":null,"end_time":null,"location":null,"description":null}}
```
(Q0=아니오: 수신 시각과 동일한 과거형 완료 알림)

### 예시 6: no_schedule / 발신자 자신의 일정 (is_schedule=false)
```
{"scenario_id":"ex_006","received_at":"2026-06-20T13:00:00+09:00","channel":"kakao","sender":"손교수","language":"ko","message":"예 그날 대구시 건축심의 회의가 14:00부터 있어 마치고 연락드릴게요..","gold":{"is_schedule":false,"title":"대구시 건축심의 회의","date":null,"time":null,"end_time":null,"location":null,"description":null}}
```
(Q1=아니오: 발신자 본인의 일정을 맥락으로 언급. 사용자 일정 아님)

### 예시 7: no_schedule / 행사 공고 (is_schedule=false, 필드 채움)
```
{"scenario_id":"ex_007","received_at":"2026-06-10T09:00:00+09:00","channel":"gmail","sender":"edu@koef.or.kr","language":"ko","message":"[KoEF] 2026 인스트럭터 역량강화 워크숍 안내 — 일시: 2026.07.18(금) 14:00~18:00 / 장소: 서울 KW컨벤션센터 / 신청 마감: 7/11(금).","gold":{"is_schedule":false,"title":"2026 인스트럭터 역량강화 워크숍","date":"2026-07-18","time":{"hour":14,"minute":0,"marker":null},"end_time":{"hour":18,"minute":0,"marker":null},"location":"서울 KW컨벤션센터","description":"신청 마감: 7/11(금)\n주최: KoEF"}}
```

### 예시 8: no_schedule / 미수락 제안 (is_schedule=false)
```
{"scenario_id":"ex_008","received_at":"2026-05-25T14:00:00+09:00","channel":"kakao","sender":"거래처","language":"ko","message":"혹시 다음 주 화요일 오후 3시 미팅 가능하실까요?","gold":{"is_schedule":false,"title":"미팅","date":"다음주화","time":{"hour":3,"minute":0,"marker":"오후"},"end_time":null,"location":null,"description":null}}
```
(미수락 제안 → false. 날짜·시간은 추출)

### 예시 9: multi_turn_confirmation / 스레드 확정 → is_schedule=true
```
{"scenario_id":"ex_009","received_at":"2026-05-25T10:35:00+09:00","channel":"kakao","sender":"나","language":"ko","thread_context":[{"time":"10:14","sender":"김용안","message":"6월4일 오전 9시 어떤지요?"}],"message":"좋습니다","gold":{"is_schedule":true,"title":"김용안과 미팅","date":"2026-06-04","time":{"hour":9,"minute":0,"marker":"오전"},"end_time":null,"location":null,"description":null}}
```
(본인 발신 확정 → true. title은 자연스러운 제목, ": 발신자" 패턴 없음)

### 예시 10: multi_turn_no / 스레드 합의 미달 → is_schedule=false
```
{"scenario_id":"ex_010","received_at":"2026-06-20T14:10:00+09:00","channel":"kakao","sender":"손태관(교수/)","language":"ko","thread_context":[{"time":"12:54","sender":"손태관(교수/)","message":"6/24(화) 15:00~17:00 시간 되실런지요"},{"time":"13:53","sender":"나","message":"24일은 17시 이후에 시간이 됩니다."},{"time":"14:10","sender":"손태관(교수/)","message":"그날 건축심의 회의가 14:00부터 있어 마치고 연락드릴게요.."}],"message":"네 교수님","gold":{"is_schedule":false,"title":null,"date":null,"time":null,"end_time":null,"location":null,"description":null}}
```
(교수의 건축심의는 발신자 일정 → false. "마치고 연락드릴게요"는 조건부 대기 → 합의 미달 → false)

### 예시 11: self_memo / 본인 메모 → is_schedule=true
```
{"scenario_id":"ex_011","received_at":"2026-05-25T18:30:00+09:00","channel":"sms","sender":"나","language":"ko","message":"내일 5시 김부장 미팅 3층 회의실로 변경","gold":{"is_schedule":true,"title":"김부장 미팅","date":"내일","time":{"hour":5,"minute":0,"marker":"오후"},"end_time":null,"location":"3층 회의실","description":null}}
```

### 예시 12: no_schedule / 행사+사람 장소 혼동 주의 (is_schedule=false)
```
{"scenario_id":"ex_012","received_at":"2026-06-15T09:00:00+09:00","channel":"gmail","sender":"info@dccei.kr","language":"ko","message":"대구창조경제혁신센터 초기창업패키지 모집 안내입니다. 접수기간: 2026.06.20~07.10 / 장소: 대구창조경제혁신센터","gold":{"is_schedule":false,"title":"초기창업패키지 모집 안내","date":null,"time":null,"end_time":null,"location":"대구창조경제혁신센터","description":"접수기간: 2026.06.20~07.10\n주최: 대구창조경제혁신센터"}}
```
(is_schedule=false: 모집 공고. location은 장소만. title에 location을 복제하지 말 것)
