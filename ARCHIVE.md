# ARCHIVE — 과거 라운드 이력 (동결 스냅샷)

> 2026-06-29 정리 시점에 옛 `HANDOFF.md`를 통째로 동결 보관한 것이다. **현재 할 일·최신 절차는 `HANDOFF.md`를 보라.**
> 여기 수치·"현재 배포본" 표기는 작성 당시 기준이며 지금과 다를 수 있다. 합성 라운드(r11~r34·c1/c2/c9·d5~d8 초기)와 그때의 진단·설계 맥락을 보존하는 용도.
>
> 라운드 계보(요약): r11(extract-resolve 첫 배포) → r18~r34(과발화/제목/필드/실피드백) → c1/c2/c9(criterion·3-way·2-way) → c2v13(현 배포본) → d5~d8(플랫 스키마 + 실데이터 재구축).

---

## 0-FLAT. ★★★ 플랫 스키마 마이그레이션 완료 (2026-06-28) — d5 학습 준비

**핵심 변경:** `schedule_status + events[]` → `is_schedule(bool) + title/date/time/end_time/location/description` 플랫 구조.
- ✅ **스키마**: `prompts/schema.md` 완전 재작성 (플랫 7-필드)
- ✅ **데이터**: `train.jsonl`(394건: is_schedule=true:206, false:188) + `golden.jsonl`(71건: true:22, false:49) 변환. 백업: `.pre_flat_bak`
- ✅ **평가 스크립트**: `eval_model.py` — `score_fields()` 플랫 채점, `is_schedule` acc, `final_score` 재산출(0.25+0.30+0.45)
- ✅ **프롬프트**: `generator.md`·`evaluator.md` 플랫 스키마 기준 전면 재작성 (few-shot 12개)
- ✅ **Config**: `configs/train_qwen3_0_6b.yaml` → `d5`, `configs/model_qwen3_0_6b.yaml` system_prompt 갱신
- ✅ **Android**: `ScheduleExtractor.kt`(파싱·데이터 클래스 플랫화+구형 폴백), `DateResolver.kt`(resolveEvent 단순화), `MessagePipeline.kt`(ext.event 직접 사용)
- ✅ **앱 UI**: 일정 카드 = 제목·시간·**발신자(필수)**·장소·설명 표시. **카드 탭 → 원본 메시지 앱 열기**(SMS는 발신자 대화방 딥링크, 카톡/Gmail은 앱 실행). 버튼 2개: **[삭제]**(일정 제거+등록 시 캘린더도) · **[등록하기]/[등록취소]** 토글. (구 [소스]·[캘린더] 버튼·카드탭→편집 폐지)

**다음 단계:**
1. **d5 학습**: `git push origin main` → Kaggle T4×2 DDP 학습 (`configs/train_qwen3_0_6b.yaml` run_name=d5, epochs=3, 394건)
2. **d5 평가**: merge → `eval_model.py` (golden 71건, 플랫 스키마 채점)
3. **데이터 보강**: is_schedule=false 케이스 다양성 보강(location 오추출·사람이름→장소 혼동 등)
4. **앱 재빌드**: Android Studio로 플랫 스키마 앱 재빌드 → APK 설치

**주의:** 현 배포본 앱(c2v13, 3-way 구 스키마)은 `ScheduleExtractor.parse()`의 구 스키마 폴백으로 계속 호환. 재빌드 후 교체.

---

## 0-CRITERION. ★★★ c9 4-phase 정비 완료 (2026-06-21) — 원칙 정렬

**핵심 원칙 확립:** "수신 시각 이후, 사용자 본인이 해야 할 일·지켜야 할 약속의 제목·날짜·시간·장소를 찾는다."
- ✅ **Phase 1**: `schedule_criterion.md` Q0/Q1/Q2 재정비 — 현재 이전=no / 오늘 미래=pending / 내일 이후 확정=yes
- ✅ **Phase 2**: `generator.md` + `evaluator.md` 현행 스키마(3-way, date 토큰, time 객체, 폐지 필드 제거)로 전면 재작성
- ✅ **Phase 3**: golden.jsonl(54건) 감사 — sms_real_silup11 yes→pending (신청=Q2 미확정)
- ✅ **Phase 4**: train.jsonl(1243건) 감사 — 오늘 일정 yes→pending 5건, 이미 지난 오늘 일정 yes→no 1건
  최종 분포: yes=371 / pending=321 / no=551
- ⏳ **다음**: c9 Colab L4 학습 (`configs/train_qwen3_0_6b.yaml` 준비됨) → c9 Q8_0 양자화 → 앱 재배포

---

## 0-DEPLOY. ★★★ c2v13 폰 배포 완료 (2026-06-18) — 현 배포본

**c2v13(3-way) Qwen3-0.6B 배포 완료.** Gemma 실험·Kaggle 모두 GPU 막혀(2일 대기) → 보유 최선 Qwen인 c2v13을 배포본으로 확정·배포.
- ✅ **모델**: HF c2 어댑터(`lora_c2-qwen3-0.6b.zip`, checkpoint-96) → 로컬 merge(`models/merged/c2-qwen3-0.6b`) → **Q8_0 양자화**(`models/gguf/c2-qwen3-0.6b/c2-qwen3-0.6b.Q8_0.gguf`, 610MB, **md5 `80771680e27a7b11c394b8209d7cb60c`**). Q4 금지(전 라운드 회귀). 로컬 양자화 우회(llama.cpp `build_bin`).
- ✅ **모델 정상성 검증**(llama-cli, temp0): 카카오페이 결제·적립→`schedule_status:"no"` / 박과장 내일 오후3시 주간회의→`"yes"`+date"내일"+time{3,오후}+loc"회사 3층". 3-way 판별·스키마 정합(confidence 없음) 확인.
- ✅ **앱 c2 3-way 전환**(`com.calenda`): `ScheduleExtractor` 시스템프롬프트를 c2(model_qwen3_0_6b.yaml과 글자 일치)로 + `schedule_status` 문자열 파싱(구 has_schedule 폴백) + `Extraction.detected`. `MessagePipeline` no→드롭. `EventRouter` confidence임계 폐지 → **status="yes"만 자동등록, pending은 항상 확인(예비)**. `DebugActivity`/`FeedbackExporter`(DISMISSED→`"no"`)/`EventEditActivity`(편집gold→`"yes"`, confidence 제거) 정합.
- ✅ **배포**(2026-06-18): ⚠ 폰에서 `com.calenda` **제거돼 있던 상태**(옛 r33 슬롯도 소멸) → APK 신규 설치(`assembleDebug`)+files 디렉토리 생성+gguf 푸시→**md5 일치**→force-stop. 슬롯명 고정 `calendar.Q4_K_M.gguf`(콘텐츠는 Q8_0). 빌드 막힘은 **좀비 Gradle 데몬**(Studio 아님, `--stop` 미사망)이라 PID 종료+lock dir 삭제로 해결.
- ⏳ **다음: 사용자 앱 1회 실행**(force-stop=stopped라 브로드캐스트 차단) → 실카톡 실사용 검증(과발화 죽나/pending 라우팅/yes 자동등록). DebugActivity로 3-way 즉석 확인 가능.
- 🟡 후속(Kaggle 회복 7/1 후): pending 보강(c3), Gemma A/B 재개. 시소(final~0.81) 돌파는 용량/데이터 레버.

---

## 0-C2. ★★★ c2 — has_schedule 3-way (yes/pending/no) + confidence 폐지 (2026-06-16)

**설계 전환:** binary has_schedule → **3-분류** `has_schedule: "yes"|"pending"|"no"`. 어려운 경계(기관 행사 안내 vs 내가 갈 것)를 강제 binary로 틀리는 대신 **pending(예비)으로 사용자에 위임**. 0.6B의 불안정한 confidence 보정 대신 이산 분류 → 안정적. confidence 폐지(= date/time 지름길 편향 원천).
- **yes**=확정(회의·예약·면접 — 자동등록) · **pending**=공고·안내·초대·미확정 제안(예비) · **no**=거래·통보·광고.
- 앱 라우팅: yes→자동, pending→예비(PENDING), no→무시. (ScheduleExtractor가 status 분기 — 재배포는 모델 검증 후, task §앱)
- ✅ **코드**: `schema.md`·`schedule_criterion.md`·시스템프롬프트(+요일→절대날짜 계산금지=#8 누수수정)·`eval_model`(detected=yes+pending·class_acc)·`_common`/`validate_train`/`audit_schedule` 전부 3-way, confidence 제거.
- ✅ **데이터**: 원본 2133(events 보존)을 Haiku 3-way 재라벨 → 풀 yes 805/pending 215/no 1099. `build_c2_assemble` → **train.jsonl 915**(yes 350·pending 215·no 350, no비 38%). 날짜누수 4 제외.
- ✅ **골든**: ⚠ **API 사용한도 소진(7/1 회복)** 으로 Haiku 불가 → **규칙기반 3-way 매핑**(54건: yes 14·pending 17·no 23, 검토 완료). r34 골든(events 보존)에서 매핑.
- ⏳ **다음: config c2(epochs=3) → push → Kaggle 학습 → 3-way 평가.** ★관전: ① pending 클래스가 학습되나(215로 충분?) ② 거래/광고 no로 가나(과발화↓) ③ yes/pending 구분(class_acc).
- 🟡 후속: pending 보강(c3, API 회복 후), 앱 status 라우팅 재배포, generator.md 새 스키마.

---

## 0-C1. (이전) c1 — criterion 기반 리베이스 1000셋 (2026-06-16)

**근본 진단:** has_schedule 과발화의 원인 = **"날짜·시각=일정" 지름길**. 학습셋 P(양성|날짜+시각)=**0.74**(음성의 date/time 보유 23%뿐). 이건 **가이드가 만든 것** — schema가 "날짜+시간+활동=일정 확정"이라 라벨러가 그렇게 찍음. r34에서 음성만 더 부어도 안 통한 이유(가이드가 반대로 당김).

**해결: 판단을 데이터에 위임 + 단일 기준(SOT) 신설.**
- ✅ **`prompts/schedule_criterion.md`** = 양/음 판단 단일 기준. **추출(date/time)과 판단(has_schedule) 분리** — "날짜·시각 존재 ≠ 일정, 사용자가 그 시각에 참석·수행할 약속만 양성". **A(단일 메시지=내용 종류)와 B(멀티턴=대화 확정여부)를 다른 잣대**로. generator·evaluator·golden 공용.
- ✅ **재감사**(`audit_schedule.py`, Haiku, criterion 주입): 기존 2133 재판정 → **양성→음성 181 교정**(배송통보 51·과거회고 30·**마감/공고/신청/납부 46**·거래 등). **결정: 마감·공고·납부=음성**(특정시각 참석 아님). 골든도 동일 재감사(g09/g10 등 9건 음성).
- ✅ **생성**(`build_c1_negatives.py`, Haiku+criterion): 멀티턴 미확정 음성 180 → audit 이중검증 **180/180 음성확인**. (양성은 재사용, generator.md는 옛 스키마라 양성 생성 불가 → 후속 갱신 필요)
- ✅ **조립**(`build_c1_assemble.py`) → **train.jsonl 1000**: A 단일 600(양300/음300) + B 멀티 400(양183/음217), **51.7% neg**. ★음성 날짜·시각 23→**66%**, **P(양성|날짜+시각) 0.74→0.57**(base 0.48 근접 = 지름길 약화). 옛 train은 `.pre_c1bak`, 전체 정리 풀은 `_audited.jsonl`(확장용).
- ⏳ **다음: config c1(epochs=3) → push → Kaggle 학습 → golden 평가.** ★관전: ① 실카톡 음성(카카오페이·스타벅스·KB·헬로오토) 과발화 죽나(핵심) ② recall(양성 적어진 골든 19개라 측정력 약함 — 미탐 늘면 음성과다) ③ 멀티턴 확정/미확정 구분.
- 🟡 후속: golden 양성 보강(19→), 35 neg→pos flag(실약속) events 추출 복원, generator.md 새 스키마+criterion 갱신.

---

## 0-NOW. ★ r34 데이터 준비 완료 — r33 실사용 진단이 처방 (2026-06-15)

**r33 실사용 진단(동일 입력 재추론, `docs/_cal.db` 폰 DB ↔ r33 Ollama 재현):** golden 0.944지만 **실제 카톡 분포에서 실패**. golden이 실사용을 예측 못 함이 드러남.
- 🔴 **실카톡 음성 과발화**: 서비스/금융 알림(카카오페이 적립·스타벅스 결제·카드 승인)·영업 로지스틱스("오후에 연락드리겠습니다"·"견적 보내드립니다")·인사말(월요일 안부)을 **일정으로 등록**. 학습 음성에 이 분포가 없었음. (r32·r33 동일 — "truncated r32" 가설은 오진, 모델 한계)
- 🔴 **대구TP류**: 긴 행사명에 무시간 시각환각(14:00/12:00) + 제목→location 복제 — r33 하드케이스 38이 이 표면형 못 덮음.
- 🟡 **김현민 중복**: 머지 2키 모두 사망 — `room=''`(KakaoTalk이 EXTRA_CONVERSATION_TITLE 미제공) + 모델이 메시지마다 다른 title·틀린 start(6/15 09:00 vs 6/13 13:00, 정답 6/16 13:00) → 폴백키 불일치. **앱(방 미캡처)+모델(날짜 불안정) 합작.**

**r34 데이터(완료, 학습 대기):**
- ✅ `build_r34_hardcases.py` → `_r34_add.jsonl` **43건**(음성 37: 서비스알림14·로지스틱스10·인사말8·지나가는언급5 + 양성 6: 긴행사명 무시간/무장소 time:null·loc:null). 실메시지 verbatim 복사 안 함(변형) — 누수 방지.
- ✅ **golden 50→54**: r33이 과발화한 **실제 카톡 음성 4건**(헬로오토 인사·KB "오후에 연락"·스타벅스 Buddy Pass·카카오페이 적립) held-out 추가 → eval이 실분포 측정. (양성28·음성26=48%)
- ✅ `apply_r34.py --apply` → train.jsonl **2133**(양성1114·음성1019=**47.8%neg**), resolve 0실패. validate 결함 0.1%·attendee 분포 건강. config r33→**r34**.
- ⏳ **다음: `git push origin main` → Kaggle r34 학습 → 양자화(Q8_0) → 배포.**
- 🟡 **앱 트랙(별도, r34 학습과 병행 가능)**: 방캡처 폴백(EXTRA_CONVERSATION_TITLE 비면 notification key/shortcut-id) · URL-단독 메시지 일정 억제 · thread 윈도우 확대.

---

## 0. 현재 배포본 — r33 Qwen3-0.6B / Q8_0 (2026-06-15)

- ✅ **r33 배포 완료(2026-06-15).** `r33-qwen3-0.6b.Q8_0.gguf`(767MiB, md5 `3755763b938d8f2d01fbc7486e5cda1b`) 폰 푸시·**md5 대조 일치**·force-stop·앱 재실행(수집 재가동). 구 r32 슬롯은 `.r32-bak` 백업. **⚠ 발견: 직전 r32 슬롯이 639MB로 truncated**(767MB여야 정상 — 무선 푸시 끊김으로 손상된 채 운용됐을 가능성). r33은 full Q8_0 무결성 확인. **실사용 검증 대기**(대구TP 제목/장소·무시간 시각환각).
  - r33 평가(golden 50): final **0.9437**(=Q8_0=FP16, r32 0.9446 동급) · time **0.92** · TP title 0.963 · location_f1 0.858 · 과발화 2·미탐 1. Q4_K_M은 회귀(0.869)라 배포 금지. train.jsonl **2090**(필드 재라벨 + 환각억제 하드케이스 38). [[train-jsonl-append-workflow]]
- ✅ **r33 = 필드 정합 + 환각 억제** (r32 자연제목 보존 위에): location 채움전용·제목복제 금지, attendees 본문 grounded만, 무시간→`time:null`. 상세 §0-A.
- ✅ **온디바이스 Qwen3-0.6B, Q8_0 배포.** Q4_K_M은 r31·r32·r33 모두 회귀 → **Q8_0 고정**. 어댑터 HF `sooryong9885/Calenda-Qwen3-0.6B`. 학습=빈 `<think></think>` non-thinking.
- ✅ **제목 설계 = 자연제목 보존** (r31 "AWS 교육팀과 줌회의"→"AWS 교육" 분해실패 후 전환). 모델 title=메시지 일정제목을 **시간만 제외, 최대한 보존**(활동-only 분해 폐기). compose_title은 **발신인 태그만**(`{제목} [발신인(소속)]`). [[title-natural-preservation]]
  - r32 평가: final **0.9446**, **title_f1 0.947**(r31 0.907→), TP title **0.977**, recall 0.964, time 0.92, 과발화 2. 데이터 train.jsonl **2052**(Haiku 전체 재라벨 681 + golden 15 + r32 조직팀 하드케이스 23). [[train-jsonl-append-workflow]]
  - 실사용 검증: "AWS 교육팀 줌 미팅" → 제목 완전 보존 ✅.
- ✅ **앱 (com.calenda, r32 전부 배포):** Q8_0 슬롯(md5 검증, r31=`.r31-bak`) · 신뢰도 float버그 수정(자동등록) · **캘린더 필드배치**(장소·참석자→description, **물리 장소만→EVENT_LOCATION**·온라인 제외) · **URL 추출**(줌·구글밋·팀즈·지도 링크→description) · **location==title 가드**(제목복제 제거) · 모델명 `R32-Q3-0.6B-Q8` 표시.
- ⚠ **Kaggle 3-A(양자화) llama.cpp 빌드 실패** → r32는 **로컬 양자화 우회**(HF 어댑터→merge_lora→`/d/llama.cpp/build_bin/llama-quantize.exe`). 다음 라운드도 동일 우회 가능(merge/quant 로컬 환경 OK: torch-cpu·peft).
- ⚠ **무선 adb 불안정**(포트 회전·대용량 푸시 끊김): 폰 화면 켜고 무선디버깅 화면 띄우면 안정. mDNS 시리얼 `adb-R3CY50525WX-...` 사용(포트 자동추적).

---

## 0-A. ★ r33 데이터 준비 완료 (2026-06-15) — push→Kaggle 학습만 남음

- ✅ **필드 정합 재라벨** `scripts/relabel_fields_haiku.py` (Haiku) — 양성 gold의 location·attendees 재생성. **보수적 가드**: location=채움 전용(기존 장소·공항 보존, 빈칸만 grounded 값으로), attendees=(기존∪Haiku) 중 **메시지 본문 grounded 이름만**(발신자 자신·미근거 제거). title/date/time 등 불가침. train+golden 동일 적용(라벨 규약 일치). 검증: 제거된 attendee 214건 중 본문-grounded 오제거 **0건**.
  - train: location 826→**869**, attendees 311→**189행**(미근거 정리), location==title은 전부 실제 장소(연남동 카페·미용실류). golden: location 5채움·attendee 2제거(정원구/김용안=발신자, compose_title 태그로 표시 유지).
- ✅ **환각 억제 하드케이스** `scripts/build_r33_hardcases.py` → `_r33_add.jsonl` **38건**: 무시간→`time:null`(18, KPI직결 시각환각 억제) · 무장소→`location:null`(12, 제목복제 억제) · 무근거 trailing잡담→`description:null`(8). resolve 0실패.
- ✅ `scripts/apply_r33.py --apply` → train.jsonl **2090행**(양성 1108·음성 982=**47.0%neg**), resolve 0실패. validate_train: 결함 0.1%, attendee 분포 고름(최다 2.1%, 포이즌닝 無).
- ✅ `prompts/schema.md` 갱신: time:null/location 제목복제 금지/attendees [] 명시. `configs/train_qwen3_0_6b.yaml` run_name·output_dir r32→**r33**.
- ✅ **Kaggle 노트북 운영성 보강**(`calendar_kaggle.ipynb`): 클론 셀이 `run_name`·`r33_` 하드케이스 건수 자동 표시(push 누락 즉시 감지) + 라운드 설정 셀이 HF_TOKEN env 설정(rate-limit 경고 제거). 상세 §3.
- ✅ **r33 학습·평가 완료 (golden 50)**: final **0.9437**(r32 0.9446 ≈ 동급) · time_match **0.92**(KPI 유지) · TP time_acc 0.963 · **TP title 0.963**(건강) · location_f1 0.858 · recall 0.964 / spec 0.909(과발화 2·미탐 1, r32 동일 프로파일).
  - title_f1 헤드라인 0.920(r32 0.947↓)은 **제목 회귀 아님** — 실패 4건 중 제목실패 0, detection 실패 3건(미탐1·과발화2)이 결합지표로 title=0 동반계산된 아티팩트. TP title 0.963이 제목 건강 증명.
  - **실패 4건 골든 감사 = 라벨 오류 0건**(전부 적합): g01(정확, 모델 경쟁날짜 오추출 1/28→2/2) · g17(정확, 사후 자료공유 과발화) · **g10**(양성 유지: 마감안내, conf 0.8<앱임계 0.85 → **PENDING/예비=사용자 확정 필요**, 사용자 컨벤션 확정) · **ad_000**(음성 유지: 미수락 골프조인 요청알림, 등록 안 함, 사용자 컨벤션 확정).
- ✅ **양자화 완료·Q8_0 무손실 검증**(golden 50): **Q8_0 = FP16 완전 일치**(final 0.944 / time 0.920 / loc 0.858, 실패 4건 동일). **Q4_K_M 회귀**(final 0.869 / time 0.760 / 과발화 2→6 / spec 0.727) — r31·r32 패턴 재확인. → **배포본 = `r33-qwen3-0.6b.Q8_0.gguf`** (Q4 금지). [[direction-ondevice-qwen3-06b]]
- ✅ **폰 배포 완료(2026-06-15):** adb(192.168.1.23:39277) push→**md5 일치**→`.r32-bak` 백업→force-stop→앱 재실행. → ⏳ **실사용 검증 대기**(대구TP 제목/장소·무시간 시각환각). 모델명 표기 `R33-Q3-0.6B-Q8`. [[feedback_reopen_app_after_gguf_swap]]
  - **배포 파일**: `r33-qwen3-0.6b.Q8_0.gguf` (767.5MB, **md5 `3755763b938d8f2d01fbc7486e5cda1b`**), HF `sooryong9885/Calenda-Qwen3-0.6B/r33-qwen3-0.6b/`. git_commit 1763255(r33 데이터)로 학습 확인.
  - **앱 슬롯**(고정명): `ModelStore.FILE_NAME = calendar.Q4_K_M.gguf` @ `getExternalFilesDir` = `/sdcard/Android/data/com.calenda/files/calendar.Q4_K_M.gguf` (슬롯명은 Q4지만 콘텐츠는 Q8_0 — r32와 동일). 모델 버전은 gguf 메타(`general.name=r33-qwen3-0.6b`)에서 자동 표시.

### r34 백로그 (r33 실패 4건·사용자 컨벤션 기반)
1. **마감형 종일 recall**(g10): 마감 안내("신청 ~날짜")를 **양성 detect + moderate conf(~0.78)** → 앱 예비(PENDING)로. 현재 모델 미탐. 소량 양성 보강.
2. **경쟁 날짜 disambiguation**(g01): 본문에 이벤트일(1/28)과 맥락 월("2월 중") 병기 시 **명시 이벤트일 우선**. 장문 격식메일 date 정확도.
3. **장문 격식메일 필드 환각**(g01): location/description을 본문 구절에서 잘못 긁음 — r33이 짧은 메시지는 잡았으나 장문은 천장.
4. **과발화 2 음성**: 사후 자료공유 격식메일(g17)·미수락 서비스 초대알림(ad_000) — 소량 음성 또는 앱 휴리스틱 우회(0.6B 천장 가능).

---

## 0-B. (실행됨) r33 데이터 방향 (자연제목 유지 + 필드 정합 + 환각 억제)

**진단(r32 실사용):** 제목 자연보존은 성공. 그러나 모델이 **보조 필드를 안 채우거나 잘못 채움**:
- `location` 비움(제목에만 보존) → 앱 새 필드배치(장소→설명/지도)가 빈 채. 또는 **제목을 location에 복제**(대구TP간담회 케이스, 앱 가드로 임시방어).
- 무시간 맥락 언급에 **시각 환각**(대구TP에 14:00 지어냄) — **시각이 최우선 KPI라 가장 심각**.
- description 환각("이후 사진을 보냅니다").

**목표:** 제목 자연보존 유지 + **location·attendees 필드를 메시지 근거로 정확히** + **환각 억제**.

1. **필드 정합 재라벨 (Haiku)** — `relabel_titles_haiku.py` 확장(또는 신규 스크립트)로 양성 gold의 **location·attendees 필드도 재생성**:
   - `location`: 실제 장소/도구(줌·강남역·회사3층)면 채움, 없으면 **null**, **제목 복제 금지**.
   - `attendees`: 실제 참석자(사람·팀)면 채움, 없으면 `[]`.
   - `title`은 r32 그대로(자연보존). title-only 재라벨이 아니라 **필드 동시 검증**.
2. **환각 억제 하드케이스** `build_r33_hardcases.py`:
   - **무시간 → `time:null`/종일** (맥락 언급·"마치고 가면 늦을 것" 류 — KPI 직결).
   - **무장소 → `location:null`** (긴 행사명, 장소 미언급).
   - **무근거 → `description:null`**.
3. **schema.md 갱신**: location/attendees 필드 규칙(있으면 채움·없으면 null·**제목복제 금지**) + 무시간 `time:null` 명시.
4. (선택·낮은 우선) 잔존 과발화 2(자료공유 격식메일·골프조인 서비스알림) 음성 소량 — 0.6B 천장 가능.
5. **assemble → push → Kaggle r33 학습 → 로컬 양자화(Q8_0) → 배포.** append 워크플로(`assemble_train --apply 금지`). configs run_name·output_dir r32→r33.

**전제 유지:** 음성비 ~48%, Q8_0 배포, ANTHROPIC_API_KEY(.env) 필요(Haiku 재라벨).

- 아래 §1·§2(구 r19/r22 메모)는 휴리스틱 맥락 참고용으로만(점수·배포본 수치는 위가 최신).

---

## 1. (이전) 현재 상태 (2026-06-07)

- ✅ **r19 폰 배포 완료(현재 배포본)** — 제목충실+그룹누적 라운드. `real_golden **48**` 기준 final **0.903**, **specificity 0.71→0.81**(과발화 9→4), 모임어휘 학습("동기회" 단독/donggi4 정확). gguf `R19 Qwen0.5B` Q4_K_M(397MB) md5 검증 푸시, 앱(roster+병합+DB v4) 설치, force-stop. 직전 r18은 `.r18-bak`.
  - ⚠ **부분 성공**: 번호목록+thread 과부하 시 제목 여전히 흔들림(donggi3="기타 회의"), 참석자 추출 불완전(3~4명 중 2명) = 0.5B 한계. → **앱 roster파싱+방-인지 병합**으로 우회(배포됨). **on-device 검증 필요**(아래 §2).
- ✅ r18(0.871/43) 이전 배포본. r17 회귀(자기참조 풀 잠식)→r18 base_r16 동결 복구. [[project_assemble_cap_erosion]]
- ✅ **0.5B 유지 확정**. 병목은 모델크기 아니라 **precision(과발화)**. recall은 천장(1.0), time도 양호(~0.93). 남은 큰 공백은 **specificity ~0.71** 하나.
- ✅ **앱: 캘린더 선택**(OAuth 없이 기기 캘린더 피커, 설정+온보딩) → 자동등록 대상 캘린더 지정. 종일 일정 **UTC 자정 버그 수정**(DTSTART/EVENT_TIMEZONE=UTC). `PREFERRED_ACCOUNT=sooryong.byun@gmail.com`.
- ✅ **앱: 재수신 검출**(시간 인지 중복제거 — `dedupeKey`에 receivedAt + 10초 창) → 같은 메시지 다른 시각 재수신 시 다시 검출. ScheduleHeuristics에 단독 "N일" 인식 추가.
- ✅ **앱: 카드·상세 메타 통일** — 채널·수신시각(M/d HH:mm)·신뢰도·등록상태를 카드와 편집 화면 동일 표시(`formatReceived` 공용). 버튼 [삭제]/[등록↔등록취소] · 네온블루(#00C2FF) 테마·로고.
- ✅ **아이덴티티 통일** → `sooryong.byun@gmail.com`(앱 상수·UI 문구·git author·캘린더 계정·피드백 수신).
- ✅ **r19 도구 일습 완성**(아래 §2) — ingest_feedback / anonymize / assemble_train --anonymize.

### r18 성적 (real_golden 43)
| recall | specificity | time(TP) | final |
|---|---|---|---|
| ~1.0(놓침 0) | **~0.71(잔여 약점)** | ~0.93 | **0.871** |
- detection recall·time은 포화. **남은 점수 손실은 거의 전부 과발화(specificity)** — 합성 음성은 r13~r16 내내 부었어도 정체(diminishing returns). → r19는 **실피드백**이 레버.

---

## 2. 당장 할 일 — r22 배포 완료(현 배포본) → 실사용 검증

**r22 배포 완료(2026-06-10).** gguf `r22-qwen0.5b.Q4_K_M.gguf`(380MB, md5 `b9859014db8318dda69be493e92401b1`) 폰 푸시·md5 대조·force-stop 완료, r19는 `.r19-bak` 백업. **사용자 앱 1회 열기 후 실사용 관찰 단계.** merge/quant 로컬 산출물: `models/merged/r22-qwen0.5b`, `models/gguf/r22-qwen0.5b/`(전 Q레벨).

**r22 평가(real_golden 50): final 0.891(역대 최고), recall 0.964(놓침1=g10), specificity 0.818(과발화 7→4), time 0.84/TP 0.923.** ①anonymizer 오염 제거가 핵심 — 실패 14건 어디에도 "민준" 없음(loc 환각도 소멸). ③격식메일·재난경보 음성이 g17/g18/sms_027 과발화 3건 제거. 실사용 실패(출금 FP·출범식 FN) 둘 다 해결 유지.

**실사용 관찰 포인트(다음 세션):** ① 출금 거래알림이 더는 등록 안 되나 ② 격식 Gmail 행사(출범식류)가 잡히나 ③ 참석자/제목에 "민준" 환각 사라졌나 ④ 카톡 동기회 번호목록(donggi3류)은 앱 roster파싱+방병합으로 한 카드 유지되나.

**잔여(r23 후보):** 과발화 4(광고2·제3자1·g19 "일정"키워드) — 광고/제3자는 앱 휴리스틱 우회 검토 / g10 마감형 종일 양성 미탐(recall) / donggi3 번호목록은 0.5B 천장(앱 우회) / start-leakage(date·time 토큰 대신 절대 start 출력) 소수.

---

### (이전) r22 학습 설계 — anonymizer 오염 수정이 헤드라인

**r21 평가(real_golden 50): final 0.855, recall 1.0(놓침 0), specificity 0.682(불변), time 0.926→0.889.** r21 음성 72는 **공고형(g15)만** 고침. 자료공유(g17)·회람(g18)·일정확인(g19)은 거의 verbatim 음성을 넣었는데도 **잔존**(0.5B가 ~10/형으론 못 꺾음) + 신규 산불 재난경보 FP. **진짜 발견: `--anonymize`가 학습셋을 오염시키고 있었다** — `_pseudo_for`의 per-record counter가 각 레코드 첫 이름을 항상 `_PSEUDO_KO[0]="민준"`으로 찍어 **train의 43%(784행)가 "민준"**. 모델이 실일정(친환경차 사업설명회)에도 title "민준과 카페"를 뱉음. r19~r21 전 라운드(+현 배포 r19)가 같은 오염.

**r22 설계(2026-06-10) — 3대 수정:**
- **① 🔴 anonymizer "민준" 오염 수정** (`anonymize.py`) — per-record counter → **이름 해시 분산**(같은 이름=같은 가명, 충돌은 선형탐사). 검증: 민준 784→**2행**, attendee 45개 이름 고르게. + `_ORG_HINT`에 공공기관 키워드(기상청·재난·행안 등) 보강 → 재난경보 발신자 가명화 방지.
- **② 보일러플레이트 description null** (`assemble_train.normalize_gold`) — base/thread/cowork에 박힌 "스레드 협의 확정" 295행을 일괄 null화(모델이 그대로 외워 환각). 검증: 295→**0**.
- **③ 잔존 confident FP 음성 강화** (`build_r22_hardcases.py`, 57건) — 자료공유·회람·일정확인 ~10→~25/형(볼륨 돌파) + 재난경보(#CMAS#·기상청) 음성 12.
- **유지:** 음성비 50% + grounding 컷(r21에서 무해·recall 1.0 확인).

**r22 상태(학습만 남음):** `train.jsonl` **1940건**(971 pos / 969 neg = **50%**, +g22 음성 57, --anonymize[수정판] 적용), `real_golden` 50건 유지, `configs/train.yaml` r22, assemble SOURCES에 r22_hardcases(keep).
→ **다음 액션: `git push origin main` 후 Kaggle 노트북으로 r22 학습** → merge/quant/eval → 배포(§3·§4). [[feedback_push_before_cloud_training]]
→ **관전 포인트:** ① 오염 제거로 **title/attendee/loc·time 대폭 회복** 기대(r21 title_avg 0.810). ② g17/g18/g19가 25/형으로도 안 죽으면 **0.5B 천장 인정**(앱 측 격식메일 발신자 휴리스틱으로 우회 검토). g10 마감형 양성은 r23 후보.

**Gmail 풀바디 API(스캐폴딩됨, 빌드/Cloud 남음):** `android/GMAIL_API.md` 참조. 코드(GmailApiClient·GmailSyncWorker·Settings 버튼·SettingsStore·deps·INTERNET) 다 들어감. **사용자 할 일**: ① Google Cloud OAuth 클라이언트(Android, pkg `com.calenda` + 디버그 SHA-1, 프로젝트=Calenda `gen-lang-client-0576056861`) + 동의화면 gmail.readonly + 테스트 사용자, 게시="테스트". ② Studio Gradle Sync 후 빌드(이 환경에서 컴파일 미검증). ③ 본문중간-일정 메일로 검증.

---

### (이전) r19 배포 완료, 실사용 테스트 중 (2026-06-07)

배포본 = r19 gguf + 앱(roster파싱·방병합·참석자캘린더제외·무-churn·설정재구성·온디바이스AI라벨). 사용자가 앱 열고 동기회 그룹 메시지 검출까지 확인함.

**실사용에서 관찰할 것**(다음 세션에 결과 받아 이어감):
1. **그룹 누적 = 한 일정인가** — 동기회처럼 번호목록 늘어나는 카톡에서 카드가 하나로 묶이나, 아니면 여러 개 생기나. (제목 "동기회" 유지? 참가자 바뀌어도 일정 안 흔들리나?)
2. **방이름 캡처** — 병합 1순위 키가 카톡 `EXTRA_CONVERSATION_TITLE`(room) 의존. 그룹알림이 이 값을 주는지가 관건. 안 주면 baseTitle 병합 폴백(제목 흔들리면 미병합) → 대안 필요.
3. 실업 SMS·일반 모임 제목 충실, 참석자가 캘린더에 안 들어가는지.

**검증 도구(다음 세션용)** — 앱 DB 직접 확인이 가장 확실(디버그 빌드):
```
# Windows: /tmp 말고 프로젝트 경로 사용. adb는 SDK 절대경로, MSYS_NO_PATHCONV=1.
adb exec-out run-as com.calenda cat databases/calenda.db > ./cal.db
# sqlite로 detected_events의 title/baseTitle/room/attendees 확인 → 병합·방캡처 판정
```
room= 로그가 필요하면 KakaoNotificationListener/MessagePipeline에 room 로깅 한 줄 추가가 빠름(현재 미로깅).

**잔여(관찰 결과 따라)**: 방이름 미캡처 시 그룹 병합 대안(첫 메시지 시각창+텍스트 유사도) / 번호목록+thread 제목 안정화용 r20 데이터 / 월-일("6/16") date 토큰 resolver 지원 / 실피드백 수집→r20.

---

## (참고) r19 설계 — 제목 충실도 + 그룹채팅 통합 (할루시네이션 제거)

**방향 전환(2026-06-07).** 실사용에서 카톡/SMS 일정이 쓰레기로 생성됨(`docs/카톡화면.jpg`·`문자화면.jpg`·`앱화면.jpg`). 배포 r18 로컬 추론으로 **원인 진단 = 데이터 문제(0.5B 한계 아님)** 확정:
- "6/16 동기회 참석 1.강상욱…" → title **"기타 회의"**(할루시네이션) + 4인 버전은 **2개 일정 분리 + 설명 통째 창작**. SMS는 "인터넷" 누락 + 무시간 00:00 + 전화번호 제목 부착.
- 능력 프로브: 동창회/회식/등산은 **정확 추출**, 오직 "동기회 참석"만 "기타 회의"로 창작 → 활동명사 복사 능력은 있음, **"동기회" 어휘 희소 + "참석"→"회의" 연상이 데이터 문제**. [[project_r19_real_feedback_driven]]

### 2-A. 데이터 (주 레버, **착수함**) — `scripts/build_r19_hardcases.py`
1. **informal 모임 title-faithful 양성** — 동기회·동창회·회식·번개·송년회·워크샵·스터디·등산·MT… gold `title`=메시지 활동구 **그대로**(일반어 "회의/협의" 창작 금지). 특히 `동기회+참석` 계열 집중.
2. **번호목록 참석자 + 그룹 누적 멀티턴** — `thread_context`로 번호목록이 늘어나는 대화. 각 메시지 gold = **같은 title("동기회")·같은 date**, attendees=목록 전체. (멀티턴 '확인'→'누적' 확장.)
3. **모임테마 하드네거티브** — "동기회 회비 입금 안내"·"지난 동창회 사진"·광고 등 = `has_schedule:false`(과발화 방지, [[feedback_boost_negative_balance]]).
4. **무시간→`time:null` 종일** — 00:00 부착 버그 교정.
- 직접생성·로컬검증([[feedback_direct_data_gen_over_paid]]). assemble: pool=base_r16 동결, keep 추가, --apply→push. [[project_assemble_cap_erosion]]

### 2-B. 앱 / resolver — **구현됨**(빌드 통과)
- **룸-인지 병합**(`EventRepository.save`) — `(채널 + start + 모델원제목 baseTitle)` + 방이름(best-effort) 키로 `findMergeable` → 기존 일정에 **attendees union** + 제목 재조합, 새 카드 없음(null 반환). DB v3→v4(`room`·`baseTitle` 컬럼), 카톡 방이름=`EXTRA_CONVERSATION_TITLE`. ★ baseTitle은 r19 모델이 안정 출력해야 병합이 걸림(현재 모델은 제목 흔들려 미병합).
- **`compose_title` 정리**(`_common`+`DateResolver` 미러) — 전화/이메일형 발신자 제목 부착 금지(`_is_machine_sender`), 참석자≥3이면 제목=활동만. 단위검증 8/8.
- 미해결: 월-일 명시 "6/16" date 토큰 resolver 지원(현재 미지원, gold는 절대ISO). 병합 시 캘린더 일정 attendees 동기화(현재 DB카드만 갱신; 대개 PENDING이라 등록 시점엔 union 반영).

### 2-C. 평가 — **구현됨**
- `real_golden` 43→**48**: 동기회 누적(3·4인, thread+번호목록, **익명화**)·실업인증 SMS(무시간 종일)·회식·송년회(held-out 제목충실). 학습(build_r19_hardcases)과 표면형 분리(누수 방지).

### 2-D. 실피드백 수집 (병행, 흡수됨)
이 실패들이 곧 피드백 데이터. 앱 캡처(`FeedbackExporter`, 무시/편집 위주)는 계속 유효 — 모이면 `ingest_feedback.py`→`assemble_train --anonymize`로 합류. 도구 준비됨(§아래).

### 2-E. 장기
- Ollama Q4 양자화 손실 검증(MX150/Vulkan 출력 빈손 — CPU 강제). [[project_hardware_constraints]]

> **도구(준비됨):** `ingest_feedback.py`(export→pairs, EDITED 절대일자→검증 상대토큰) / `anonymize.py`+`assemble_train --anonymize`(PII 스크럽, message↔gold↔thread↔sender 일관 가명, 시간토큰 불가침). `data/feedback_raw/` gitignore.

---

## 3. 학습 한 라운드 (Colab L4, 권장 경로)

`notebooks/calendar_colab.ipynb`를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습.

- ⚠️ **학습 전 반드시 `git push origin main`** — 노트북이 `git clone`으로 최신 데이터를 가져오므로, 푸시 안 하면 이전 라운드 데이터로 돈다.
- 라운드 올릴 땐 `configs/train_qwen3_0_6b.yaml`의 `run_name`·`output_dir` 두 곳만 변경.
- Colab 세션 종료 전 **즉시 lora zip 다운로드** (세션 정리 시 `/content/` 삭제됨).
- 로컬: zip → `models/lora/cN/` 압축해제 → `merge_lora.py` → `eval_model.py` → `quantize.sh`. (merge/quant/eval은 `.venv` 로컬, 학습만 Colab.)
- bf16(품질) 유지.
- ⚠️ **`num_train_epochs`는 3 고정.** 2로 줄이면 언더핏 회귀(recall·time KPI 저하). `load_best_model_at_end`가 best epoch을 고르므로 3이 과적합 위험 없음. 시간 단축은 **데이터 축소**로.

명령 요약은 `CLAUDE.md` §8.

---

## 4. 배포 절차 (gguf 교체)

1. `merge_lora.py` → `quantize.sh`(또는 convert+llama-quantize) → `models/gguf/rN/rN.Q4_K_M.gguf`.
2. (선택) Ollama 로컬 Q4 검증: `Modelfile`(FROM **절대경로** + SYSTEM=model_qwen.yaml) → `ollama create -f Modelfile <name>`. ※ FROM 상대경로면 "invalid model name" 에러.
3. adb push → md5 대조 → 옛 슬롯 `.rN-1-bak` 백업 → 교체 → `am force-stop`.
4. ⚠️ **사용자가 앱을 한 번 열어야** SMS/카톡 수집 재가동(force-stop=stopped 상태는 브로드캐스트 차단). [[feedback_reopen_app_after_gguf_swap]]
5. resolver(`DateResolver.kt`)나 앱 코드가 바뀌었으면 **앱도 재빌드**(installDebug).

---

## 5. 행동 원칙 / 함정

- **시각 정확도가 최우선 KPI.** title/timezone 퍼지는 허용. [[feedback_time_first_priority]]
- **앱 빌드**: 보통 Android Studio에서. CLI `gradlew :app:installDebug`도 됨 — **단 Studio를 닫고**(`gradlew --stop`) 해야 Kotlin 데몬 충돌·`app/build` 잠금 안 남. (`app/.cxx` 네이티브 캐시는 `app/build`와 별도라 보존됨.) [[feedback_android_build_in_studio]]
- **카톡 자가전송은 검출 불가**(내가 보낸 메시지엔 알림 안 뜸 → NotificationListener 캡처 없음). 실수신만. SMS는 자가전송도 수신문자로 와서 잡힘.
- 합성 데이터는 에이전트가 직접 생성 + 로컬 무료 검증 우선(유료 Haiku 파이프라인 보조). [[feedback_direct_data_gen_over_paid]]
- 음성 비율 ~40% 유지(낮추면 과발화). [[feedback_boost_negative_balance]]
- `build_user_block` 입력 포맷 바꾸면 train·eval·앱(`DateResolver`/`ScheduleExtractor`) 세 곳 함께. `_common.py`↔`DateResolver.kt`는 항상 미러.
- PAT/OAuth/API 키를 채팅에 붙여넣지 말 것 — getpass에 사용자가 직접 입력. [[feedback_never_share_secrets]]

---

## 6. 트러블슈팅 메모

| 증상 | 원인 / 해결 |
|------|------------|
| 배포 후 검출 안 됨 | force-stop/재설치 후 **앱 미실행(stopped)** → 브로드캐스트 차단. **앱 한 번 열기.** logcat `MessagePipeline: onMessage`로 캡처 발생 확인. |
| 카톡만 검출 안 됨 | 자가전송이면 정상(알림 없음). 실수신 + 그 방 닫아둔 상태여야. |
| 점수가 낮아 보임 | 결합 메트릭은 과발화 1건이 title/time/loc 동반 0처리 → 디커플링 지표(extraction_on_true_positives)로 진짜 추출력 확인. 골든은 대체로 건강(r15 감사 완료). |
| Ollama 출력 빈손 | MX150 2GB/Vulkan 이슈(0.30 기본 Vulkan). CPU 강제 또는 보너스라 스킵. 모델 자체는 fp16 eval로 검증됨. |
| `ollama create` "invalid model name" | Modelfile FROM이 상대경로 → 절대경로로. |
| 모델 계보 헷갈림 | 폴더 mtime 말고 내부 파일 mtime + adapter sha256. |
| 한글 깨짐(PowerShell/cp1252) | `PYTHONUTF8=1`. merge/eval 콘솔 크래시 방지. |
| Colab 학습물 증발 | 세션 종료 시 `/content/` 삭제됨. 학습 끝나면 즉시 lora zip 다운로드. |
| 빌드 `Unable to delete directory ...dataBindingGenBaseClasses/...out` (Defender 등 on-access 스캐너 ↔ Gradle 삭제 경합, 잠금이 매 실행 다른 generated 폴더로 이동) | ① `gradlew --stop` + java(gradle/kotlin) 프로세스 전부 kill ② **막힌 `app/build/generated/data_binding_base_class_source_out`(또는 해당 out)를 PowerShell로 선제 삭제** ③ `gradlew :app:assembleDebug --no-daemon --no-watch-fs`. 삭제 대상이 비면 태스크는 생성만 하므로 경합 소멸. 근본해결은 `Add-MpPreference -ExclusionPath D:\calenda`(관리자). |

---

## 7. 사용자 정보

- 이름: Soo (`sooryong.byun@gmail.com` — 앱·git·캘린더·피드백 수신 전부 통일). 한국어 대화 선호, 기술 용어 영어 OK.
- 머신: Windows 11, MX150 2GB VRAM (로컬=데이터/merge/quantize/검증, 학습=클라우드 GPU). Ollama 0.30.6.
- 작업 폴더: `D:\calenda`(GitHub `sooryong/Calenda`). 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
