# HANDOFF — 지금 당장 무엇을 할 것인가

> 세션 시작 시 가장 먼저 읽는 파일. 전체 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md`.

---

## 0. 현재 배포본 — r30 Qwen3-0.6B (2026-06-14)

- ✅ **방향 전환: 0.5B(r22) → Qwen3-0.6B(r30)**. hybrid 폐기, 온디바이스 Qwen3-0.6B 확정(2026-06-13). 학습=빈 `<think></think>` non-thinking 프리필(strip 금지, 의도된 설계). 어댑터는 HF `sooryong9885/Calenda-Qwen3-0.6B` 백업.
- ✅ **r30 학습→merge→양자화→평가→폰배포 전부 완료·검증.**
  - 평가(`logs/eval_r30-qwen3-0.6b.json`, real_golden 50): **final 0.9376(역대 최고)**, recall **1.0**(놓침 0), specificity **0.909**(과발화 2), time_match **0.92**, title_f1 0.904.
  - gguf 산출: `models/gguf/r30-qwen3-0.6b/`(Q4_K_M 396MB / Q8_0 / f16). 폰 슬롯 `calendar.Q4_K_M.gguf` **md5 `f1e8d5775676dd8c2d4a576050dcfa98` 일치 검증**.
- ✅ **앱 패키지 통일** `com.vibezent.calendaragent` → **`com.calenda`**(namespace=applicationId, 앱이름 "Calenda"). 폰 **신규 설치**(2026-06-14 11:03), 구 `com.calendaragent` 제거됨. 빌드 성공(`android/build_log.txt`). ⚠ OAuth 클라이언트도 새 패키지 `com.calenda`로 재발급 필요(Gmail API 쓸 때).
- 🔄 **r31 진행 중(데이터·코드 준비 완료, 학습 남음)** — 설계: **장소를 표시 제목에 합성 + 신뢰도 장소 의존 제거**(실사용 "줌 미팅"이 0.85·예비된 분석에서).
  - ✅ 앱 버그: 자동등록 신뢰도 비교 Float/Double 경계(`0.85>=0.85f`=False) 수정(`EventRouter`, `-1e-4`).
  - ✅ `compose_title`(_common·DateResolver 미러): location을 ` @{장소}`로 제목 합성, 발신인 `[이름(소속)]`. 형식 `[참석자와] 활동 [@장소] [발신인(소속)]`. location 필드·캘린더 장소칸 유지.
  - ✅ schema.md: 온라인 도구(줌·구글밋·팀즈·전화)도 location, 신뢰도 루브릭 장소 의존 제거.
  - ✅ 데이터 `train.jsonl` 1961→**2029**(음성 48%): r31 하드케이스 68(온라인장소24·물리6·온라인음성12 + **r30 골든 5실패 보완** neg_third8·neg_svc6·confirm6·formal6) + confidence 재bump 197. `configs/train_qwen3_0_6b.yaml` r31.
  - ⏳ **남음: push → Kaggle r31 학습**(§3) → merge/quant/eval(골든 5실패 개선 확인) → 폰 배포(§4) + 앱 재빌드(DateResolver 바뀜). r30 어댑터는 HF·로컬 백업본 존재.
- 아래 §2(r22 시점 메모)는 데이터/앱 휴리스틱 맥락 참고용으로만(점수·배포본 수치는 위가 최신).

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
adb exec-out run-as com.calenda cat databases/calendar-agent.db > ./cal.db
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

## 3. 학습 한 라운드 (Kaggle, 권장 경로)

`notebooks/calendar_kaggle.ipynb`를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습.

- ⚠️ **학습 전 반드시 `git push origin main`** — 노트북이 `git reset --hard origin/main`으로 clone하므로, 푸시 안 하면 이전 라운드 데이터로 돈다(r15에서 겪음). clone 후 `grep -c gNN_ data/processed/train.jsonl`로 확인. [[feedback_push_before_cloud_training]]
- 라운드 올릴 땐 `configs/train.yaml`의 `run_name`·`output_dir` 두 곳만 rN→rN+1. (eval_golden=`data/eval/real_golden.jsonl` 43건.)
- ⚠️ **실피드백이 섞인 라운드(r19~)는 `assemble_train.py --anonymize`로 train.jsonl 생성** 후 push — 실 사적 메시지 PII 제거(§2-B).
- T4 **2개** → cell이 `torchrun --nproc_per_node=2` DDP. 끝나면 **즉시 zip 다운로드**(세션 정리가 `/kaggle/working` 삭제).
- 로컬: zip → `models/lora/rN/` 압축해제 → `merge_lora.py` → `eval_model.py` → `quantize.sh`. (merge/quant/eval은 `.venv` 로컬, 학습만 클라우드.)
- bf16(품질) 유지. fp16(`train_colab.yaml`)은 ~5점 낮음 — Colab T4 단독일 때만 임시.

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
| Kaggle 학습물 증발 | 세션 정리. 끝나면 즉시 zip. |

---

## 7. 사용자 정보

- 이름: Soo (`sooryong.byun@gmail.com` — 앱·git·캘린더·피드백 수신 전부 통일). 한국어 대화 선호, 기술 용어 영어 OK.
- 머신: Windows 11, MX150 2GB VRAM (로컬=데이터/merge/quantize/검증, 학습=클라우드 GPU). Ollama 0.30.6.
- 작업 폴더: `D:\calenda`(GitHub `sooryong/Calenda`). 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
