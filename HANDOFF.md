# HANDOFF — 지금 당장 무엇을 할 것인가

> 세션 시작 시 가장 먼저 읽는 파일. 전체 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md`.

---

## 1. 현재 상태 (2026-06-06)

- ✅ **r16 폰 배포 완료** — `models/gguf/r16-qwen0.5b/r16-qwen0.5b.Q4_K_M.gguf`(380MB) → adb push(md5 검증) → 폰 슬롯 `/sdcard/Android/data/`**`com.calendaragent`**`/files/calendar.Q4_K_M.gguf`(applicationId 경로!). 설정 화면에 **"R16 Qwen0.5B"** 표시 확인됨. 직전 r15는 `.r15-bak`로 폰에 보관.
- ✅ **데이터→학습→배포 파이프라인 r16까지 한 바퀴 검증**: 데이터(직접생성 hardcases) → Kaggle bf16 학습 → merge → quantize → 폰 push → 앱 재빌드. SMS 실수신 검출·자동등록 logcat으로 확인.
- ✅ **평가 메트릭 개선**(`eval_model.py`): 결합 지표 외에 **디커플링** 추가 — `detection`(recall/specificity/과발화·놓침) + `extraction_on_true_positives`(올바로 검출된 양성 한정 title/time/loc). + **deadline 완화**: start가 날짜만이면 날짜로 비교(all_day↔시각 둘 다 정답). 진단용 `scripts/audit_eval.py`(per-item 덤프).
- ✅ **resolver 보강**(`_common.py`+`DateResolver.kt` 미러, schema.md 갱신): 단독 **"N일"**(가까운 미래 N일) + **요일 별칭**(`이번목요일`→`이번주목`). r15 실패 sms_real_000/009 해결.
- ✅ **앱 변경 다수 배포**: 카드 [삭제][등록] UX + 등록상태/편집 + 엄격 자동등록(이제 **장소 요구 제거**, 제목+시간만) / 설정·디버그 **모델 버전·업로드시각 표시** / 섹션 제목 강조색·구분선 / 메인 카운트 숫자 다크 라벤더 / 상단 상태바 겹침 해결(fitsSystemWindows) / 파이프라인 진단 로그.
- ✅ **0.5B 유지 확정**(과거 r12에서 0.5B≈1.5B 무승부, 1.5B 3배 비용 → 0.5B). 병목은 모델크기 아니라 **precision(과발화)**.

### r16 성적 (real_golden 43, 공정 메트릭)
| recall | specificity | title(TP) | **time(TP)** | loc(TP) | final |
|---|---|---|---|---|---|
| 1.000 | 0.571 | 0.882 | **0.909** | 0.768 | 0.827 |
- r15 대비: time 0.81→**0.91**, loc 0.61→0.77, recall 0.955→**1.0**(놓침 0). **단 specificity 0.62→0.57**(과발화 8→9) — precision이 유일한 후퇴/잔여 약점.

---

## 2. 당장 할 일 (다음 요청 때 이어서)

**r16은 배포·검증 끝.** 남은 단 하나의 약점은 **과발화(precision, specificity 0.57)**. 다음 우선순위:

1. **피드백 루프 가동(최우선)** — r14/r15/r16에서 합성 음성을 계속 넣었지만 과발화는 **거의 안 잡힘(diminishing returns)**. 실제 over-fire는 합성 분포와 안 맞음. 앱이 add/dismiss/edit를 학습페어로 캡처(`FeedbackExporter`, 설정에서 opt-in 전송, 임계 10건)하니 **실사용 누적 → 실 dismiss 데이터로 r17 음성 보강**이 진짜 레버. [[project_incremental_learning_feedback]]
2. **(보조) r17 합성** — 정말 더 할 거면 r16 실패셋(`data/failures/round_latest.jsonl`, 13건 — 과발화 9가 대부분)의 **그 패턴에 더 밀착**한 음성. 단 효과 제한적 예상.
3. **장기** — Ollama로 Q4 양자화 손실 검증(현재 MX150/Vulkan에서 출력 빈손 이슈 — CPU 강제 모드로 살릴 수 있음). [[project-hardware-constraints]]

---

## 3. 학습 한 라운드 (Kaggle, 권장 경로)

`notebooks/calendar_kaggle.ipynb`를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습.

- ⚠️ **학습 전 반드시 `git push origin main`** — 노트북이 `git reset --hard origin/main`으로 clone하므로, 푸시 안 하면 이전 라운드 데이터로 돈다(r15에서 겪음). clone 후 `grep -c gNN_ data/processed/train.jsonl`로 확인. [[feedback_push_before_cloud_training]]
- 라운드 올릴 땐 `configs/train.yaml`의 `run_name`·`output_dir` 두 곳만 rN→rN+1. (eval_golden=`data/eval/real_golden.jsonl` 43건.)
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

- 이름: Soo (`soo@vibezent.com`). 한국어 대화 선호, 기술 용어 영어 OK.
- 머신: Windows 11, MX150 2GB VRAM (로컬=데이터/merge/quantize/검증, 학습=클라우드 GPU). Ollama 0.30.6.
- 작업 폴더: `D:\calendar-agent`. 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
