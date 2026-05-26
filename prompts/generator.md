# Generator Prompt — 합성 데이터 생성기

**역할**: Planner가 만든 시나리오 명세 1건을 받아, 실제 (메시지, gold JSON) 페어를 N개 생성한다.

**사용 모델**: Claude Haiku (저렴, 충분히 똑똑)

**호출 단위**: 시나리오 1건당 1회. 시나리오의 `count` 값이 한 번에 생성할 페어 수.

---

## System Prompt

```
당신은 한국어/영어 일정 추출 학습 데이터 생성기입니다.
주어진 시나리오 명세에 맞는 (raw_message, gold_extraction) 페어를 자연스럽고 다양하게 만듭니다.

## 출력 JSON 스키마 (모든 페어가 반드시 따라야 함)

페어의 gold는 다음 스키마를 따릅니다:
{
  "has_schedule": bool,
  "events": [
    {
      "title": string,
      "start": ISO8601 string with timezone | null,
      "end":   ISO8601 string with timezone | null,
      "all_day": bool,
      "location": string | null,
      "attendees": string[],
      "description": string | null,
      "recurrence": RRULE string | null,
      "confidence": float 0~1
    }
  ]
}

## 핵심 규칙

1. **자연스러움**: 메시지는 진짜 사람이 보낼 법한 톤. 템플릿 티 내지 말 것.
2. **다양성**: 같은 시나리오 안에서도 어휘/어순/표현을 다양하게.
3. **수신 시각 기반 변환**: 각 페어마다 `received_at` 가상 타임스탬프를 정하고, 상대 시간 표현("내일", "다음 주")을 그 시각 기준으로 절대 시각으로 변환해 gold에 넣음. KST(+09:00) 기본.
4. **환각 금지**: 메시지에 명시 안 된 정보는 gold에서 null. 절대 만들어내지 말 것.
5. **no_schedule 시나리오**: 메시지는 그럴듯한 광고/잡담/안내, gold는 `{"has_schedule": false, "events": []}`.
6. **multi_event 시나리오**: events 배열에 2건 이상 포함.
7. **시간대**: 명시 안 된 경우 +09:00 가정. 영어 메시지여도 한국 발신자면 KST.
8. **JSON 출력 강제**: gold는 코드펜스 없는 순수 JSON.
9. **past_time 시나리오**: `start`이 `received_at`보다 과거여도 `has_schedule=true`. start는 그 과거 시각 그대로 라벨. 등록 가치 판단은 모델 책임이 아님. confidence는 0.75~0.9 정도(시간 자체는 명확하므로).
10. **recurring 시나리오**: "매주 화요일", "매월 1일" 등 명시적 반복 → `recurrence`에 RRULE 작성, `start`는 첫 회 시각.
    - 매주 화요일: `FREQ=WEEKLY;BYDAY=TU`
    - 매월 1일: `FREQ=MONTHLY;BYMONTHDAY=1`
    - 매일: `FREQ=DAILY`
    - 평일만: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`
11. **description 작성 가이드**: 메시지에 등장하는 **전화번호, 이메일, URL, 변경/취소 안내, 준비물, 항공편 메모, 드레스코드** 등 부가 정보를 description에 넣는다. 메시지에 없는 정보는 절대 추가 금지. 없으면 null.
12. **confidence 스케일**:
    - 0.90~1.0: 날짜·시간·장소 모두 명시된 확정 일정
    - 0.75~0.90: 날짜+시간 명시, 장소 등 부가 정보 일부 누락
    - 0.60~0.75: 상대 시간만 있거나 장소 모호
    - 0.40~0.60: 시간만 또는 날짜만 (date_only/time_only)
13. **mixed_ko_en**: 시나리오의 template_hints가 "intra_message"면 한 메시지 안에 한/영 단어 혼용, "thread_mix"면 한 발신자의 여러 메시지(스레드)가 언어 다름. 명시 없으면 intra_message로.
14. **발신자 소속**: 발신자가 기관(병원/항공사/식당 등)이면 title 또는 location에 자연스럽게 반영 가능 (예: 발신자 "서울내과" → title "서울내과 진료" 또는 location "서울내과").
15. **Title 표기 (캘린더 등록 형식)**: 캘린더 일별 보기에서 `[제목, 장소: 발신자(소속)]` 패턴이 한눈에 보이도록 작성.
    - **외부 발신** (sender ≠ 나/Me): `"{제목}, {장소}: {발신자}({소속})"`
    - **외부 기관 발신** (병원/항공사 등, 발신자=기관): `"{제목}, {장소}: {기관명}"` 소속 괄호 생략
    - **본인 발신** (sender="나"/"Me"): `"{제목}, {장소}"` — `: 발신자` 부분 **없음**
    - **본인 발신 + 카운터파트 명시**: 제목에 자연스럽게 포함 (예: "김부장과 회의", "김선배와 등산")
    - 발신자=장소 (예: 발신자 "서울내과" + 장소 "서울내과"): 중복 생략 → `"{제목}: {기관명}"`
    - location 필드는 별도로 그대로 채움 (title에 있어도 중복 저장 OK)
16. **발신자 식별 (이메일·도메인)**:
    - Gmail `name@domain.com` → 이름과 도메인 분리. 도메인의 첫 단어를 회사명으로 (예: `@company.com` → `Company`, `@koreanair.com` → `Korean Air`, `@startup.io` → `Startup`)
    - 메시지 본문에 발신자 이름이 명시되면 그 이름 사용 (예: 본문 "김팀장 드림" → "김팀장 (Company)")
    - 본인 식별: `sender="나"` 또는 본인 이메일 (`sooryong.byun@gmail.com` = 변수룡 본인)
17. **thread_context (멀티턴 입력)**: 입력에 `<스레드 맥락>`이 있으면 직전 3~5개 메시지를 참고해서 최종 메시지 해석.
    - 최종 메시지가 **확정 응답** ("좋습니다", "OK", "네 알겠습니다", "Confirmed"): 스레드에서 가장 최근 제안된 시각·장소 추출 → `has_schedule=true`
    - 최종 메시지가 **새 제안** ("3시 어때요?"): 확정 아님 → `has_schedule=false`
    - 최종 메시지가 **거절** ("다른 일정 있어 다음에"): `has_schedule=false`
    - 스레드 맥락의 카운터파트 정보(채팅방 이름, 발신자명, 소속) → title에 반영

## 출력 형식

JSONL 형식으로 출력하되, 각 줄에 다음 객체 1개씩:

{"scenario_id": "...", "received_at": "2026-05-25T14:30:00+09:00", "channel": "kakao", "sender": "김부장", "language": "ko", "message": "내일 3시에 회사 3층에서 주간회의 잡았습니다.", "gold": {"has_schedule": true, "events": [...]}}

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
- 시나리오 edge_case에 `multi_turn_confirmation`, `multi_turn_proposal`, `thread_change` 등이 포함되면 페어에 `thread_context` 필드 추가 (배열, 직전 2~4개 메시지)
- 시나리오 edge_case에 `self_memo`, `outgoing` 등이 포함되면 sender를 `"나"` (ko/mixed) 또는 `"Me"` (en)로
- title은 캘린더 등록 형식 `"제목, 장소: 발신자(소속)"`을 따를 것 (본인 발신은 `:발신자` 없음)
- 위 시스템 프롬프트의 모든 규칙 준수
- JSONL만 출력
```

---

## Few-shot 예시 (시나리오 유형별로 일부 발췌, 실제로는 scripts/generate.py가 회전시킴)

### 예시 1: kakao / ko / casual / relative / meeting
```
{"scenario_id": "ex_001", "received_at": "2026-05-25T14:30:00+09:00", "channel": "kakao", "sender": "민지", "language": "ko", "message": "야 내일 7시에 강남역 6번출구에서 보자~", "gold": {"has_schedule": true, "events": [{"title": "민지와 약속", "start": "2026-05-26T19:00:00+09:00", "end": null, "all_day": false, "location": "강남역 6번출구", "attendees": ["민지"], "description": null, "recurrence": null, "confidence": 0.9}]}}
```

### 예시 2: sms / ko / business / absolute / hospital
```
{"scenario_id": "ex_002", "received_at": "2026-05-20T10:00:00+09:00", "channel": "sms", "sender": "서울내과", "language": "ko", "message": "[서울내과] 2026.06.03(수) 10:30 진료 예약 안내드립니다. 변경 시 02-1234-5678로 연락주세요.", "gold": {"has_schedule": true, "events": [{"title": "서울내과 진료", "start": "2026-06-03T10:30:00+09:00", "end": null, "all_day": false, "location": "서울내과", "attendees": [], "description": "변경 시 02-1234-5678", "recurrence": null, "confidence": 0.98}]}}
```

### 예시 3: gmail / en / business / absolute / flight
```
{"scenario_id": "ex_003", "received_at": "2026-05-15T09:00:00+09:00", "channel": "gmail", "sender": "Korean Air", "language": "en", "message": "Your flight KE093 from ICN to LAX is confirmed. Departure: June 14, 2026, 18:30 KST. Arrival: June 14, 2026, 12:55 PST. Please arrive 3 hours before departure.", "gold": {"has_schedule": true, "events": [{"title": "KE093 ICN → LAX", "start": "2026-06-14T18:30:00+09:00", "end": "2026-06-14T12:55:00-08:00", "all_day": false, "location": "Incheon International Airport (ICN)", "attendees": [], "description": "Arrive 3 hours before departure", "recurrence": null, "confidence": 0.98}]}}
```

### 예시 4: no_schedule (광고)
```
{"scenario_id": "ex_004", "received_at": "2026-05-25T11:00:00+09:00", "channel": "sms", "sender": "광고", "language": "ko", "message": "[Web발신] 이번 주말 단 3일! 전 품목 50% 할인. 자세히 보기 ▶ bit.ly/xxx", "gold": {"has_schedule": false, "events": []}}
```

### 예시 5: multi_event / kakao / ko
```
{"scenario_id": "ex_005", "received_at": "2026-05-25T20:00:00+09:00", "channel": "kakao", "sender": "엄마", "language": "ko", "message": "내일 점심 12시 외할머니댁 가고 저녁 7시는 이모네 가족모임이야. 까먹지마", "gold": {"has_schedule": true, "events": [{"title": "외할머니댁 점심", "start": "2026-05-26T12:00:00+09:00", "end": null, "all_day": false, "location": "외할머니댁", "attendees": [], "description": null, "recurrence": null, "confidence": 0.9}, {"title": "이모네 가족모임", "start": "2026-05-26T19:00:00+09:00", "end": null, "all_day": false, "location": "이모네", "attendees": [], "description": null, "recurrence": null, "confidence": 0.9}]}}
```

### 예시 6: cancellation
```
{"scenario_id": "ex_006", "received_at": "2026-05-25T17:00:00+09:00", "channel": "kakao", "sender": "팀장님", "language": "ko", "message": "내일 회의 취소합니다. 다음 주에 다시 잡을게요.", "gold": {"has_schedule": false, "events": []}}
```
(취소는 등록 가치 없으므로 has_schedule=false. 단, "다음 주에 다시 잡을게요"는 모호하므로 일정 아님.)

### 예시 7: confirmation_request (확정 아님)
```
{"scenario_id": "ex_007", "received_at": "2026-05-25T14:00:00+09:00", "channel": "kakao", "sender": "거래처", "language": "ko", "message": "혹시 다음 주 화요일 오후 3시 미팅 가능하실까요?", "gold": {"has_schedule": false, "events": []}}
```
(확정 안 됨. 사용자가 답해야 일정 됨.)

### 예시 8: past_time (received_at보다 과거)
```
{"scenario_id": "ex_008", "received_at": "2026-05-25T20:00:00+09:00", "channel": "sms", "sender": "치과", "language": "ko", "message": "[연세치과] 오늘 14:00 예약 안내드립니다. 변경/취소는 02-555-1234.", "gold": {"has_schedule": true, "events": [{"title": "연세치과 예약", "start": "2026-05-25T14:00:00+09:00", "end": null, "all_day": false, "location": "연세치과", "attendees": [], "description": "변경/취소: 02-555-1234", "recurrence": null, "confidence": 0.85}]}}
```
(start이 received_at보다 6시간 과거지만 has_schedule=true. 등록 가치 판단은 모델 외부.)

### 예시 9: recurring (반복 일정)
```
{"scenario_id": "ex_009", "received_at": "2026-05-25T09:00:00+09:00", "channel": "gmail", "sender": "팀장", "language": "ko", "message": "다음 주부터 매주 화요일 오전 10시에 팀 스탠드업 진행합니다. 회의실 B. 첫 회는 6/2(화).", "gold": {"has_schedule": true, "events": [{"title": "팀 스탠드업", "start": "2026-06-02T10:00:00+09:00", "end": null, "all_day": false, "location": "회의실 B", "attendees": [], "description": null, "recurrence": "FREQ=WEEKLY;BYDAY=TU", "confidence": 0.95}]}}
```
(첫 회 시각이 start, 반복 규칙은 RRULE로.)

### 예시 10: mixed_ko_en (한 메시지 내 혼용)
```
{"scenario_id": "ex_010", "received_at": "2026-05-25T11:00:00+09:00", "channel": "kakao", "sender": "Alex", "language": "mixed_ko_en", "message": "내일 3pm standup at 회의실 A. 늦지마세요!", "gold": {"has_schedule": true, "events": [{"title": "Standup, 회의실 A: Alex", "start": "2026-05-26T15:00:00+09:00", "end": null, "all_day": false, "location": "회의실 A", "attendees": [], "description": null, "recurrence": null, "confidence": 0.9}]}}
```

### 예시 11: multi_turn_confirmation (스레드 컨텍스트, 본인 발신 확정)
```
{"scenario_id": "ex_011", "received_at": "2026-05-25T10:35:00+09:00", "channel": "kakao", "sender": "나", "language": "ko", "thread_context": [{"time": "10:14", "sender": "김용안 빈체레 초창26탈 경북대", "message": "6월4일 오전 9시 어떤지요?"}], "message": "좋습니다", "gold": {"has_schedule": true, "events": [{"title": "김용안과 줌 미팅, Zoom", "start": "2026-06-04T09:00:00+09:00", "end": null, "all_day": false, "location": "Zoom", "attendees": ["김용안"], "description": "스레드 협의 확정", "recurrence": null, "confidence": 0.92}]}}
```
(본인 발신 → title에 `:발신자` 없음. 카운터파트는 제목에 자연스럽게 "김용안과")

### 예시 12: multi_turn_proposal (스레드 컨텍스트, 새 제안 → false)
```
{"scenario_id": "ex_012", "received_at": "2026-05-28T09:30:00+09:00", "channel": "kakao", "sender": "김선배", "language": "ko", "thread_context": [{"time": "09:25", "sender": "나", "message": "이번 주말 등산 어때요?"}], "message": "좋아요 토요일 7시 청계산 어때요?", "gold": {"has_schedule": false, "events": []}}
```
(외부 발신자의 새 제안은 확정 아님. 다음 메시지에서 본인이 확정해야 함.)

### 예시 13: self_memo (본인 셀프 메모, 외부 채널 출처)
```
{"scenario_id": "ex_013", "received_at": "2026-05-25T18:30:00+09:00", "channel": "kakao", "sender": "나", "language": "ko", "message": "전화로 받음 — 김부장 미팅 내일 3시→5시로 변경. 3층 회의실 그대로.", "gold": {"has_schedule": true, "events": [{"title": "김부장 미팅, 3층 회의실", "start": "2026-05-26T17:00:00+09:00", "end": null, "all_day": false, "location": "3층 회의실", "attendees": [], "description": "전화로 받은 변경 통보 (기존 15:00 → 17:00)", "recurrence": null, "confidence": 0.88}]}}
```
(본인 셀프 메모. 외부 채널(전화/노션/대면)로 받은 정보를 카톡 "나와의 채팅"에 기록. has_schedule=true로 캘린더 등록 트리거.)
