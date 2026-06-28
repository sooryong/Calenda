# HANDOFF — 지금 당장 무엇을 할 것인가

> 세션 시작 시 가장 먼저 읽는 파일. 전체 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md`.
> 과거 라운드(r11~r34·c1/c2/c9·d5~)의 진단·설계 이력은 `ARCHIVE.md` 참조.

---

## 0. 현재 단계 (2026-06-29) — 실데이터 재구축 + d8 학습

**방향 전환:** 그동안의 합성 라운드(r·c 계열)를 전부 폐기하고, **실제 SMS/카톡/Gmail 수집 메시지**를 true/false로 나눠 라벨링하는 방식으로 재구축한다. 모델은 플랫 스키마로 일정 유무와 필드를 추출하고, 앱이 등록을 처리한다.

- ✅ **플랫 스키마**: `is_schedule`(bool) + `title / date / time / end_time / location / description` (단일 이벤트). `sender·channel·received_at`은 모델 출력이 아니라 앱·데이터 페어가 캡처하는 메타데이터(입력 블록 주입). 분류 기준 = `prompts/schedule_criterion.md`(yes/no 2-way).
- ✅ **데이터**: `data/processed/train.jsonl` **371건**(is_schedule true/false 혼합) · `data/eval/golden.jsonl` **50건**. 원본 실메시지 풀은 `data/raw/`(sms_all.txt·kakao/ 등). 백업: `*.pre_flat_bak`.
- ✅ **코드 플랫화 완료**: `eval_model.py`(플랫 채점·is_schedule acc), `generator.md`·`evaluator.md`, 앱(`ScheduleExtractor`/`DateResolver`/`MessagePipeline`). extract-resolve·멀티턴(`build_user_block`) 유지.
- ✅ **앱 카드 UI 개편**: 카드 탭 → 원본 메시지 앱 열기(SMS는 발신자 대화방 딥링크, 카톡/Gmail은 앱 실행) · 발신자 필수 표시 + 장소·설명 · 버튼 [삭제]·[등록하기]/[등록취소]. (구 [소스]·[캘린더] 버튼·카드탭→편집 폐지)
- ⏳ **학습 config = d8**: `configs/train_qwen3_0_6b.yaml` run_name=`d8-qwen3-0.6b-lora`, epochs=3, output `models/lora/d8-qwen3-0.6b`.

🟡 **배포본은 아직 c2v13 Q8_0**(구 3-way 스키마). 앱이 구스키마 폴백으로 호환 중. **d8 학습·평가 통과 후 교체.**

---

## 1. 다음 할 일

1. **d8 학습**: `git push origin main` → Kaggle T4×2 DDP(또는 Colab L4)로 학습. ⚠ 학습 전 반드시 push(노트북이 clone으로 최신 데이터를 가져옴).
2. **d8 평가**: merge → `eval_model.py`(golden 50, 플랫 채점) → **Q8_0 양자화**(Q4_K_M 금지, 회귀).
3. **데이터 보강**: `is_schedule=false` 다양성(거래·결제·광고·공고/안내·남의 일정·미수락 제안, location 오추출). 실수집 풀(`data/raw/`)에서 추가 라벨링.
4. **앱 재빌드**: 카드 UI 변경 반영 위해 Android Studio 재빌드 → APK 설치(gguf 교체 없이 앱만). gguf까지 교체하면 §3 배포 절차.

---

## 2. 학습 한 라운드 (Colab L4, 권장 경로)

`notebooks/calendar_colab.ipynb`를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습.

- ⚠️ **학습 전 반드시 `git push origin main`** — 노트북이 `git clone`으로 최신 데이터를 가져오므로, 푸시 안 하면 이전 라운드 데이터로 돈다.
- 라운드 올릴 땐 `configs/train_qwen3_0_6b.yaml`의 `run_name`·`output_dir` 두 곳만 변경.
- Colab 세션 종료 전 **즉시 lora zip 다운로드** (세션 정리 시 `/content/` 삭제됨).
- 로컬: zip → `models/lora/dN/` 압축해제 → `merge_lora.py` → `eval_model.py` → `quantize.sh`. (merge/quant/eval은 `.venv` 로컬, 학습만 Colab.)
- bf16(품질) 유지.
- ⚠️ **`num_train_epochs`는 3 고정.** 2로 줄이면 언더핏 회귀(recall·time KPI 저하). `load_best_model_at_end`가 best epoch을 고르므로 3이 과적합 위험 없음. 시간 단축은 **데이터 축소**로.

명령 요약은 `CLAUDE.md` §8.

---

## 3. 배포 절차 (gguf 교체)

1. `merge_lora.py` → `quantize.sh`(또는 convert+llama-quantize) → `models/gguf/dN/dN.Q8_0.gguf`. (Q4_K_M 금지 — 전 라운드 회귀.)
2. (선택) Ollama 로컬 검증: `Modelfile`(FROM **절대경로** + SYSTEM=model_qwen.yaml) → `ollama create -f Modelfile <name>`. ※ FROM 상대경로면 "invalid model name" 에러.
3. adb push → md5 대조 → 옛 슬롯 `.bak` 백업 → 교체 → `am force-stop`. 슬롯명 고정 `calendar.Q4_K_M.gguf`(콘텐츠는 Q8_0).
4. ⚠️ **사용자가 앱을 한 번 열어야** SMS/카톡 수집 재가동(force-stop=stopped 상태는 브로드캐스트 차단).
5. resolver(`DateResolver.kt`)나 앱 코드가 바뀌었으면 **앱도 재빌드**(installDebug).

---

## 4. 행동 원칙 / 함정

- **시각 정확도가 최우선 KPI.** title/timezone 퍼지는 허용.
- **앱 빌드**: 보통 Android Studio에서. CLI `gradlew :app:installDebug`도 됨 — **단 Studio를 닫고**(`gradlew --stop`) 해야 Kotlin 데몬 충돌·`app/build` 잠금 안 남. (`app/.cxx` 네이티브 캐시는 별도라 보존됨.)
- **카톡 자가전송은 검출 불가**(내가 보낸 메시지엔 알림 안 뜸 → NotificationListener 캡처 없음). 실수신만. SMS는 자가전송도 수신문자로 와서 잡힘.
- 합성 데이터는 에이전트가 직접 생성 + 로컬 무료 검증 우선(유료 Haiku 파이프라인 보조).
- 음성 비율 ~40% 이상 유지(낮추면 과발화).
- `build_user_block` 입력 포맷 바꾸면 train·eval·앱(`DateResolver`/`ScheduleExtractor`) 세 곳 함께. `_common.py`↔`DateResolver.kt`는 항상 미러.
- PAT/OAuth/API 키를 채팅에 붙여넣지 말 것 — getpass에 사용자가 직접 입력.

---

## 5. 트러블슈팅 메모

| 증상 | 원인 / 해결 |
|------|------------|
| 배포 후 검출 안 됨 | force-stop/재설치 후 **앱 미실행(stopped)** → 브로드캐스트 차단. **앱 한 번 열기.** logcat `MessagePipeline: onMessage`로 캡처 발생 확인. |
| 카톡만 검출 안 됨 | 자가전송이면 정상(알림 없음). 실수신 + 그 방 닫아둔 상태여야. |
| 점수가 낮아 보임 | 결합 메트릭은 과발화 1건이 title/time/loc 동반 0처리 → 디커플링 지표(extraction_on_true_positives)로 진짜 추출력 확인. |
| Ollama 출력 빈손 | MX150 2GB/Vulkan 이슈. CPU 강제 또는 스킵. 모델 자체는 fp16 eval로 검증됨. |
| `ollama create` "invalid model name" | Modelfile FROM이 상대경로 → 절대경로로. |
| 모델 계보 헷갈림 | 폴더 mtime 말고 내부 파일 mtime + adapter sha256. |
| 한글 깨짐(PowerShell/cp1252) | `PYTHONUTF8=1`. merge/eval 콘솔 크래시 방지. |
| Colab 학습물 증발 | 세션 종료 시 `/content/` 삭제됨. 학습 끝나면 즉시 lora zip 다운로드. |
| 빌드 `Unable to delete directory ...dataBindingGenBaseClasses` (Defender ↔ Gradle 삭제 경합) | ① `gradlew --stop` + java(gradle/kotlin) 프로세스 kill ② 막힌 `app/build/generated/...out` PowerShell로 선제 삭제 ③ `gradlew :app:assembleDebug --no-daemon --no-watch-fs`. 근본해결 `Add-MpPreference -ExclusionPath D:\calenda`(관리자). |

---

## 6. 사용자 정보

- 이름: Soo (`sooryong.byun@gmail.com` — 앱·git·캘린더·피드백 수신 전부 통일). 한국어 대화 선호, 기술 용어 영어 OK.
- 머신: Windows 11, MX150 2GB VRAM (로컬=데이터/merge/quantize/검증, 학습=클라우드 GPU). Ollama 0.30.6.
- 작업 폴더: `D:\calenda`(GitHub `sooryong/Calenda`). 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
