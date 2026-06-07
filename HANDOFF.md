# HANDOFF — 지금 당장 무엇을 할 것인가

> 세션 시작 시 가장 먼저 읽는 파일. 전체 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md`.

---

## 1. 현재 상태 (2026-06-07)

- ✅ **r18 폰 배포 완료(현재 배포본)** — 동결 base_r16 + 단독 "N일" 종일 양성 보강. `real_golden 43` 기준 **final 0.871**(r16 0.827 대비 개선). r17은 자기참조 풀 잠식으로 회귀(0.779)해 폐기 → r18은 **pool=base_r16 동결**로 복구. [[project_assemble_cap_erosion]]
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

## 2. 당장 할 일 — r19 = 실피드백 주도 (데이터 수집 중)

**r18 배포·검증 끝.** 유일한 큰 약점은 **과발화(specificity ~0.71)**. 합성으론 정체했으니 **레버는 폰 실피드백**. → r19는 **실데이터가 충분히 모일 때까지 보류**하고, 그동안 앱을 써서 모은다. [[project_r19_real_feedback_driven]]

### 2-A. 지금 할 일: 실피드백 수집 (코딩 아님)
앱 캡처 = `status ∈ {ADDED, AUTO_ADDED, DISMISSED} & exported=0`. 가치순:
1. **오탐을 의식적으로 많이 거절** — 광고·업무메일·제3자·시스템알림 카드를 **메인에서 '삭제'(=무시 소프트)** 로. ★ specificity의 전부. (DISMISSED→`has_schedule:false`)
2. **틀린 추출은 지우지 말고 '편집'으로 교정** — EDITED gold(가장 깨끗).
3. **맞으면 '등록'** — 확정 양성.
- ⚠ **이벤트함(전체) '삭제'는 완전삭제(행 제거)라 학습신호 소실.** 거절은 반드시 메인 카드에서. 완전삭제는 export 후 청소용.
- 목표: export는 신규 10건↑부터. specificity를 43-eval에서 움직이려면 **무시(음성) 위주 ~40~60건**. 음성 ~40% 균형. [[feedback_boost_negative_balance]]

### 2-B. 데이터 모이면: r19 실행 (도구 준비됨)
```powershell
# 폰 → 설정 → "학습 데이터 보내기" → JSONL을 data/feedback_raw/ 에 저장 (data/feedback_raw는 gitignore)
python scripts/ingest_feedback.py --round r19        # export→학습페어. EDITED 절대일자→검증된 상대토큰
                                                     #   (_common.resolve_date 역변환, 메시지 표면형 우선,
                                                     #    미일치는 절대일자 유지+ data/feedback_raw/r19_review.jsonl)
# assemble_train.py SOURCES(라인 ~38)에 추가:
#   {"path": "data/processed/feedback_r19.jsonl", "kind": "keep", "real": True},
python scripts/assemble_train.py --anonymize         # 미리보기: PII 익명화된 train 확인(음성%·건수)
python scripts/assemble_train.py --anonymize --apply # train.jsonl 갱신(익명화 적용)
git push origin main                                 # Kaggle clone 대상 (push 전 필수) [[feedback_push_before_cloud_training]]
# 이후 §3 학습 → §4 배포
```
- **익명화**(`scripts/anonymize.py` + `--anonymize`): 실 사적 메시지를 push 전 PII 제거. message↔gold↔thread↔sender **같은 이름=같은 가명 일관 치환**, 전화·주민·카드·계좌·이메일·URL 마스킹, **날짜/시각 토큰 불가침**([[feedback_time_first_priority]]). dedup·균형은 raw로 끝낸 뒤 출력 직전에만 적용.
- 규율: **pool=base_r16 동결**, cap 여유(축출 0), 신규 전부 `keep`, 디커플링 평가. [[project_assemble_cap_erosion]]

### 2-C. 장기
- Ollama로 Q4 양자화 손실 검증(MX150/Vulkan 출력 빈손 이슈 — CPU 강제로 살릴 수 있음). [[project_hardware_constraints]]

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
- 작업 폴더: `D:\calendar-agent`. 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
