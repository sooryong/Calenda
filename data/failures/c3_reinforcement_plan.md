# c3 라운드 보강 시나리오 표 (baseline: c2 평가 round_latest-c2.jsonl)

> 현재 트랙을 c3으로 승격. 아래 표는 c2 모델의 실패 13건에서 도출한 **c3 보강 데이터**(`data/processed/c3_reinforce.jsonl`, scenario `c3r_*`)의 설계 근거.


기준 평가: `final_score 0.833 / time_match 0.778 / specificity_neg 0.76 (overfire 6) / missed 3`
출처: `data/failures/round_latest-c2.jsonl` (FP16 merged, golden n=54)

점수 출혈의 핵심은 **탐지(detection)** — 추출은 진양성에서 강함(title 0.947, time 0.885). 따라서 A·B(음성 specificity / pending recall) 우선.

## 보강 카테고리 표

| # | 카테고리 | 약점(증상) | 대표 실패 ID | 목표 출력 | 권장 합성 |
|---|---------|-----------|-------------|----------|----------|
| A | 음성 specificity (overfire 6) | "활동+모호한 시간"이면 발화 | — | `schedule_status:no, events:[]` | 60~80 |
| A1 | · 요청·문의(시간 미확정) | "일정 문의… 편하신 시간에 회신주시면" | gmail_real_g13 | no | 12 |
| A2 | · 완료·확인 통보 | "보고서 확인완료… 감사" | gmail_real_g14 | no | 12 |
| A3 | · 제3자 의무(@타인) | "@김현철 … 강의하셔야 하는 상황" | kakao_real_002 | no | 12 |
| A4 | · 멀티턴 비확정 | "네 알겠습니다 → 네" (상대가 종료) | kakao_real_006 | no | 12 |
| A5 | · 명시적 미확정 | "아마… 미확정인데 … 곧 공유" | kakao_real_008 | no | 12 |
| A6 | · 영업 팔로업 | "오후쯤 연락드리겠습니다" (영업 스레드) | real_logi_kb | no | 12 |
| B | pending recall (missed 3) | 소프트하게 표현된 pending을 no로 | — | `pending` + event | 30~40 |
| B1 | · 마감형 "~까지 신청" | "~10/13까지 신청 안내" | gmail_real_g10 | pending, all_day, date=마감일 | 12 |
| B2 | · 안내체+명시 일시 | "행사 개요 전달 … 11.2(일) 16:00~" | gmail_real_g03 | pending, date+time | 12 |
| B3 | · 짧은 개인 마감 | "11일 실업인증 인터넷 신청" | sms_real_silup11 | pending, date="11일", all_day | 10 |
| C | location=null 규율 | 기관·사람 이름을 장소로 오추출 | g01(원스톱지원실)·g15(연구소)·kakao_001(정원구 페테리안)·kakao_006(경북대)·kakao_002(모든 장소) | 실제 venue/온라인만, 아니면 null | 25 |
| D | 날짜·relative-token 규율 | ①날짜 없으면 환각 ②상대표현→토큰 ③절대계산 금지 | g15(없는데 "2025-12-01" 생성)·kakao_001(다음주월인데 절대일자 계산)·g01(2월중↔1/28 오선택) | date=null 또는 토큰, 절대일자 계산 금지 | 25 |
| E | time marker 규율 | 명시형 "09시"·"13:00"에 오전/오후 부착 | sms_005("09시 30분"+오후)·kakao_002("13:00"+오전) | 명시 24h형은 marker=null | 15 |
| F | title 위생 | 발신자 문자열을 제목에 끌어옴 | g15·kakao_001/002/006 | 활동·주제만, 발신자 분리 | (A~D에 동반) |

합계 권장 합성 ≈ 150~180건 (소량·다양 원칙). 음성(A) 비중 최우선.

## #4 (모델이 절대일자를 직접 계산) — train.jsonl 점검 결과

`train.jsonl`(994 rows) 정밀 스캔 결론: **데이터 오염 아님.**

- gold date 분포(event): absolute_ISO 362 / relative_token 246 / other 17 / null 16.
- "절대ISO gold인데 메시지엔 상대표현뿐(명시 절대일자 없음)" 진짜 위반 = **2건뿐** (362건 중).
- 멀티턴 양성 71건: relative_token 63 / absolute_ISO 8 → 상대표현→토큰 매핑은 정상 학습됨.

→ #8(kakao_001 다음주월을 2026-05-26로 계산)·#10(kakao_006)의 날짜 계산은 데이터가 아니라 **0.6B 일반화 한계**로 보임. 대량 데이터 수술 불필요. 대신 D 카테고리로 "상대표현→토큰, 절대계산 금지" 소량 강화 권장.

### 발견된 위반 2건 (수정 후보)

| scenario_id | 현재 gold date | 메시지 | 권장 수정 |
|---|---|---|---|
| kakao_ko_casual_relative_meeting_001 | `2026-06-14` | "이번 주말 오후 4시 남산 공원…" | `이번주말` (토큰) — 명백한 위반 |
| boost_085 | `2026-07-04` (recur 주간토) | "매주 토요일 오전 9시 픽업" | 재발 이벤트 — date=토큰 또는 null+recurrence (수동 판단) |

## 다음 액션

1. `plan.py --failures data/failures/round_latest-c2.jsonl` 로 폐루프 시나리오 생성 (위 A~E 비중 반영).
2. 위 train.jsonl 위반 2건 정정(특히 kakao_ko_casual_relative_meeting_001).
3. 학습 후 **Q8_0 GGUF로 골든 재평가** (배포 품질 확인).
