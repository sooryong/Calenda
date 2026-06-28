# Calendar Agent — 프로젝트 가이드 (Claude Code용)

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는 **단일 정본**이다. 프로젝트 컨텍스트·현재 단계·다음 할 일·운영 절차가 모두 여기 있다.
> **코드를 짜기 전에 반드시 이 파일과 `prompts/schema.md`를 먼저 읽어라.**
> "지금 무엇을 할 것인가"는 §12(현재 단계 + 다음 할 일)를 보면 된다.

---

## 1. 프로젝트 목표

안드로이드 폰에서 SMS / 카카오톡 / Gmail로 들어오는 메시지에서 **일정을 자동 추출해 Google Calendar에 등록**하는 에이전트.

핵심 제약: **온디바이스 LLM**(폰 예산권 ~800MB, Q8까지). **Qwen/Qwen3-0.6B**를 LoRA 파인튜닝 + GGUF 양자화(Q8_0 배포)로 폰에 올린다.

---

## 2. 학습 파이프라인 아키텍처

```
┌──────────┐   시나리오    ┌───────────┐   (input, JSON)   ┌────────────┐
│ Planner  │ ────────────> │ Generator │ ────────────────> │ Evaluator  │
│ (Sonnet) │               │  (Haiku)  │                   │ (Haiku+규칙)│
└──────────┘               └───────────┘                   └─────┬──────┘
     ▲                                                           │
     │            실패 패턴 피드백 (Active Learning Loop)          │
     └───────────────────────────────────────────────────────────┘
                                                                 ▼
                                                       ┌──────────────┐
                                                       │   Harness    │
                                                       │ 학습/양자화/배포 │
                                                       └──────────────┘
```

- **Planner** (`scripts/plan.py`, Claude Sonnet): 시나리오 명세서 생성. 초기/폐루프 두 모드.
- **Generator** (`scripts/generate.py`, Claude Haiku): 시나리오대로 (메시지, gold JSON) 페어 생성.
- **Evaluator** 두 역할:
  - 데이터 QA (`scripts/evaluate_data.py`, Haiku): 합성 데이터 accept/fix/reject
  - 모델 Judge (`scripts/eval_model.py` 내부, Sonnet): 학습된 모델 출력 평가 (규칙 기반 + LLM judge 혼합)
- **Harness**: 학습(`train_lora.py`) → merge(`merge_lora.py`) → 양자화(`quantize.sh`) → 평가 루프

> 현재는 합성 생성보다 **실제 수집 메시지(`data/raw/`)를 직접 라벨링**하는 방식이 주력이다(§12).

---

## 3. 디렉토리 구조

```
calenda/
├── CLAUDE.md             ← 이 파일 (단일 정본)
├── README.md             ← 사람용 개요
├── SETUP.md              ← 환경 구축 가이드
├── pyproject.toml        ← Python 3.10~3.14 지원 (학습 단계는 3.11 권장)
├── .env                  ← ANTHROPIC_API_KEY (gitignore)
│
├── prompts/              ← ★ 모델 호출 프롬프트 (수정 시 신중)
│   ├── schema.md             ← 단일 출력 JSON 스키마 (반드시 먼저 읽기)
│   ├── schedule_criterion.md ← is_schedule 분류 기준 (SOT)
│   ├── planner.md            ← Planner system/user 프롬프트
│   ├── generator.md          ← Generator + few-shot
│   └── evaluator.md          ← 데이터 QA + 모델 Judge 프롬프트
│
├── scripts/
│   ├── _common.py        ← Anthropic 호출, JSONL I/O, build_user_block, resolver
│   ├── plan.py / generate.py / evaluate_data.py
│   ├── train_lora.py     ← SFTTrainer + PEFT LoRA
│   ├── merge_lora.py     ← LoRA → merged FP16
│   ├── eval_model.py     ← 골든셋 평가 (플랫 스키마 채점)
│   └── quantize.sh       ← llama.cpp 양자화
│
├── configs/
│   ├── model_qwen3_0_6b.yaml  ← Qwen3-0.6B 베이스 + system_prompt
│   ├── lora.yaml             ← r=16, alpha=32
│   └── train_qwen3_0_6b.yaml ← 하이퍼파라미터 (run_name = 현재 라운드)
│
├── data/
│   ├── raw/              ← ★ 실수집 원본(SMS sms_all.txt·카톡 kakao/·Gmail) + Generator 출력
│   ├── processed/        ← QA/라벨링 통과한 학습용 (train.jsonl, val.jsonl)
│   ├── eval/             ← ★ 골든 평가셋 golden.jsonl (수동 작성, git 추적)
│   └── failures/         ← 실패 케이스 (폐루프, eval_model.py 자동생성)
│
├── models/               ← 전부 git 제외
│   ├── lora/ · merged/ · gguf/(Q8_0 배포본)
│
├── ui/streamlit_app.py   ← 데이터 검수 + 에러 분석
├── notebooks/            ← calendar_colab.ipynb / calendar_kaggle.ipynb (학습)
├── logs/                 ← 학습/평가 로그
└── android/              ← 온디바이스 앱 com.calenda (수집 + GGUF 추론 + DateResolver)
```

---

## 4. 출력 JSON 스키마 (절대 중요) — extract-resolve

전체 시스템이 이 스키마를 공유한다. **상세·토큰 어휘·resolver 표는 반드시 `prompts/schema.md`를 읽어라.** 여기는 요약만.

★ **현재 스키마 = 플랫 7-필드, 단일 이벤트.** (구 `has_schedule`+`events[]` 중첩, `marker`/`attendees`/`organizer`/`confidence`/`recurrence`/`all_day`는 폐지.)

★ **핵심 설계: 모델은 날짜·시각을 "계산"하지 않고 표면형만 "추출"한다.** 0.6B는 요일→날짜(주말 횡단)·AM/PM→24h 산술을 못 맞히므로, 모델은 `date`(상대 토큰) + `time`(시·분·표시어)만 내고, **절대 시각 계산은 resolver가 결정론적으로 수행**한다:
- Python: `scripts/_common.py` → `resolve_when` / `resolve_event` / `compose_title`
- Kotlin(앱): `android/.../DateResolver.kt` (위 Python의 미러 — 둘이 같은 표를 공유)

```json
{
  "is_schedule": true,
  "title": "AWS 교육팀 줌회의",
  "date": "내일",
  "time": { "hour": 1, "minute": 0, "marker": "오후" },
  "end_time": null,
  "location": "줌",
  "description": null
}
```

- `is_schedule`: **나의 확정 일정**이면 `true`, 거래·통보·광고·미수락 제안·공고·안내·과거이면 `false`. 분류 기준 = `prompts/schedule_criterion.md`.
- `date`: 상대 토큰(`내일`,`다음주화`,`1주후`,`이번주말`…) 또는 명시된 절대일자(`"2026-06-05"`) 또는 null. **모델은 절대일자 계산 금지.**
- `time`: `{hour, minute, marker}` 또는 null(미상·종일). marker=`오전`/`오후`/`저녁`/`정오`… 또는 null. 24h 변환은 resolver가.
- `title`: 메시지의 일정 제목/주제를 **시간 표현만 제외하고 최대한 보존**(활동-only 분해 금지). `is_schedule=false`여도 주제를 제목으로 추출.
- `location`/`description`: 있으면 채움, 없으면 null. **제목을 location에 복제 금지.** 참석자·주최자·반복·URL·전화번호 등 부가정보는 `description`에 통합.
- ★ **`sender`/`channel`/`received_at`은 모델 출력이 아니라 앱·데이터 페어가 캡처하는 메타데이터**다(입력 블록에 주입, gold JSON엔 없음). 앱 카드/`compose_title`이 발신인 태그로 사용.

### 입력 포맷 (학습/추론) — `_common.build_user_block`이 렌더
```
<채널: KakaoTalk>
<수신시각: 2026-05-25T14:30:00+09:00 (월)>      ← 요일 부착
<발신자: 김부장>
<메시지>
내일 3시에 회사 3층에서 주간회의 잡았습니다. 박과장도.
</메시지>
```
→ 모델은 위 스키마 JSON만 출력 (코드펜스 없는 순수 JSON). 위 예 기대 출력: `"date":"내일", "time":{"hour":3,"minute":0,"marker":null}` → resolver가 받은 14:30 기준 "3시"→15:00, 2026-05-26으로 변환.

**멀티턴(대화내역)**: 일정 협의가 여러 메시지에 걸치면 앱이 직전 3~5개를 `<대화내역>` 블록으로 함께 넣는다. 최종 메시지가 확정 응답("좋습니다")이면 직전 제안 시각을 추출(`is_schedule=true`), 새 제안·유보면 false. 형식은 `build_user_block`이 학습·평가·앱 공용으로 렌더 — 바꾸면 세 곳을 함께 바꿔야 한다. 상세는 `prompts/schema.md`.

---

## 5. 규약 / 컨벤션

### 프롬프트 수정 시
- `prompts/*.md`의 섹션 헤더와 ` ``` ` 펜스 구조는 **정규식으로 파싱**한다 (각 `scripts/*.py` 상단 RE 참조). 헤더 텍스트나 펜스 위치를 바꾸면 스크립트가 깨진다.
- Generator 프롬프트의 `### 예시 N:` 블록도 정규식으로 회전 사용된다.

### 데이터 형식
- 모든 데이터는 **JSONL** (한 줄에 dict 하나, `orjson` 사용).
- 페어 필드: `scenario_id`, `received_at`, `channel`, `sender`, `language`, `message`, `gold`. 멀티턴 케이스만 `thread_context`(직전 메시지 배열) 추가.
- 데이터는 라운드마다 직접 append 누적(`assemble --apply`류 전면 재조립 금지 — 과거 회귀 이력).
- 신규 train 추가 전 **golden 누수 전수 대조**(exact + difflib > 0.85), train↔golden 분리 유지.

### 모델 호출
- 모든 호출은 `scripts/_common.py`의 `call_claude()`를 거친다 — 재시도/지수백오프 내장.
- 기본 teacher 모델: Planner `claude-sonnet-4-6` · Generator/Data QA `claude-haiku-4-5-20251001` · Model Judge `claude-sonnet-4-6`.
- ⚠ **데이터 작성·수정에 Haiku API 쓰지 말 것** — criterion(Q1/Q2) 기준으로 Claude가 직접 정정.

### 행동 원칙 / 함정
- **시각 정확도가 최우선 KPI.** title/timezone 퍼지는 허용.
- **음성 비율 ~40% 이상 유지** (낮추면 과발화).
- **`build_user_block` 입력 포맷을 바꾸면 train·eval·앱(`DateResolver`/`ScheduleExtractor`) 세 곳을 함께** 바꿔야 한다. `_common.py` ↔ `DateResolver.kt`는 **항상 미러**.
- **데이터 수정 시 config `run_name`/`output_dir`을 같은 커밋에서 함께** 올린다(버전 추적 일치).
- **카톡 자가전송은 검출 불가**(내가 보낸 메시지엔 알림이 안 떠 NotificationListener 캡처 없음). 실수신만. SMS는 자가전송도 잡힘.
- **앱 빌드**는 보통 Android Studio. CLI `gradlew :app:installDebug`도 되나 **Studio를 닫고**(`gradlew --stop`) 해야 Kotlin 데몬 충돌·`app/build` 잠금이 안 남는다.
- PAT/OAuth/API 키를 채팅에 붙여넣지 말 것 — getpass에 사용자가 직접 입력.

### 라이선스 / 보안
- `.env`·시크릿(예: `configs/HF_TOKEN_Kaggle.txt`)·실수집 원본(`data/raw/` 사적 메시지)은 **절대 커밋 금지**. 모델/대용량도 git 제외. `data/eval/golden.jsonl`만 추적.

---

## 6. 베이스 모델 / 토크나이저

**단일 베이스: Qwen/Qwen3-0.6B** (`configs/model_qwen3_0_6b.yaml`)
- 한국어 양호, 토크나이저 효율 OK, LLaMA-like 구조라 LoRA target_modules 표준(q/k/v/o/gate/up/down_proj)
- thinking 모델이나 SFT gold가 순수 JSON이라 학습으로 비-thinking 고정. 추론은 빈 `<think></think>` 프리필(학습 빈 think는 의도된 설계 — strip 금지).
- 폰 예산권 ~800MB(Q8까지). **배포 양자화는 Q8_0 고정**(Q4_K_M은 매 라운드 회귀 확인 → 금지).
- 어댑터 백업: HF `sooryong9885/Calenda-Qwen3-0.6B` (Kaggle Secret `HF_TOKEN`).

(이전 Qwen2.5-0.5B / HyperCLOVA 라인은 폐기.)

---

## 7. 환경

- **Python 3.10~3.14**: 데이터 생성·평가는 3.14에서도 OK. **학습**(`pip install -e .[train]`)에서 PyTorch/bitsandbytes wheel 못 찾으면 Python 3.11 venv로 학습만.
- OS: Windows 11 (`D:\calenda`). 학습은 클라우드 GPU.
- 컴퓨팅: 로컬 = MX150 2GB(데이터/merge/quantize/검증) · 학습 = Colab Pro(L4/A100) + Kaggle T4×2.
- 의존성 단계 분리: `pip install -e .`(데이터·평가) / `.[train]`(torch·peft·trl) / `.[ui]`(Streamlit).
- 양자화: `llama.cpp` 별도 클론 + 빌드 (`scripts/quantize.sh`). 로컬 우회: HF 어댑터→merge_lora→`llama-quantize.exe`.

---

## 8. 자주 쓰는 명령

```powershell
# venv 활성화
.\.venv\Scripts\Activate.ps1

# 데이터 파이프라인 (한 라운드)
python scripts/plan.py        --out data/raw/plan_v1.json
python scripts/generate.py    --plan data/raw/plan_v1.json --out data/raw/v1.jsonl --workers 4
python scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl

# 학습 → merge → 평가 → 양자화 (학습은 Colab/Kaggle, merge/eval/quantize는 로컬)
python scripts/train_lora.py  --config configs/train_qwen3_0_6b.yaml
python scripts/merge_lora.py  --base Qwen/Qwen3-0.6B --lora models/lora/d9-qwen3-0.6b --out models/merged/d9-qwen3-0.6b
python scripts/eval_model.py  --model models/merged/d9-qwen3-0.6b --eval data/eval/golden.jsonl --out logs/eval_d9-qwen3-0.6b.json --model_config configs/model_qwen3_0_6b.yaml
bash   scripts/quantize.sh    models/merged/d9-qwen3-0.6b models/gguf/d9-qwen3-0.6b

# UI
streamlit run ui/streamlit_app.py
```

---

## 9. 학습 한 라운드 (Colab L4 / Kaggle T4×2)

`notebooks/calendar_colab.ipynb`(또는 `calendar_kaggle.ipynb`)를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습.

- ⚠️ **학습 전 반드시 `git push origin main`** — 노트북이 `git clone`으로 최신 데이터를 가져온다. 푸시 안 하면 이전 라운드로 돈다.
- 라운드 올릴 땐 `configs/train_qwen3_0_6b.yaml`의 `run_name`·`output_dir` 두 곳만 변경(데이터 커밋과 함께).
- Colab 세션 종료 전 **즉시 lora zip 다운로드**(`/content/`는 세션 정리 시 삭제).
- 로컬: zip → `models/lora/dN/` 해제 → `merge_lora.py` → `eval_model.py` → `quantize.sh`.
- bf16 유지. ⚠️ **`num_train_epochs`는 3 고정** — 2는 언더핏 회귀(recall·time↓). `load_best_model_at_end`가 best epoch을 고르므로 과적합 위험 없음. 시간 단축은 데이터 축소로.

---

## 10. 배포 절차 (gguf 교체)

1. `merge_lora.py` → `quantize.sh` → `models/gguf/dN/dN.Q8_0.gguf`. (Q4_K_M 금지 — 회귀.)
2. (선택) Ollama 로컬 검증: `Modelfile`(FROM **절대경로** + SYSTEM=model_qwen.yaml) → `ollama create`. ※ 상대경로면 "invalid model name" 에러.
3. adb push → **md5 대조** → 옛 슬롯 `.bak` 백업 → 교체 → `am force-stop`. 슬롯명 고정 `calendar.Q4_K_M.gguf`(콘텐츠는 Q8_0).
4. ⚠️ **사용자가 앱을 한 번 열어야** 수집 재가동(force-stop=stopped는 브로드캐스트 차단).
5. resolver(`DateResolver.kt`)·앱 코드가 바뀌었으면 **앱도 재빌드**(installDebug).

---

## 11. 폐루프 (Active Learning)

`scripts/eval_model.py`가 점수 낮은 샘플을 `data/failures/round_latest.jsonl`에 자동 저장. 다음 라운드 Planner를 `--failures`로 호출하면 약점 보강 시나리오 위주로 생성. eval JSON(`logs/`)·failures 파일은 Claude가 직접 읽는다(사용자 붙여넣기 불필요).

---

## 12. 현재 단계 + 다음 할 일 (2026-06-29)

**방향:** 합성 라운드(r·c 계열)를 전부 폐기하고, **실제 수집 메시지(SMS/카톡/Gmail)를 true/false로 라벨링**해 재구축. 모델은 플랫 스키마로 일정 유무·필드를 추출, 앱이 등록을 처리한다.

**상태**
- ✅ **플랫 스키마**: `is_schedule`(bool) + `title/date/time/end_time/location/description` 단일 이벤트. `schema.md`·`schedule_criterion.md`(yes/no 2-way)·`eval_model.py`·앱 전부 플랫.
- ✅ **데이터**: `data/processed/train.jsonl` ~371건(true/false 혼합) · `data/eval/golden.jsonl` 50건. 실수집 원본 풀은 `data/raw/`(sms_all.txt·kakao/). extract-resolve·멀티턴 유지.
- ✅ **앱 카드 UI 개편**: 카드 탭 → 원본 메시지 앱 열기(SMS는 발신자 대화방 딥링크), 발신자 필수 표시 + 장소·설명, 버튼 [삭제]·[등록하기]/[등록취소].
- ⏳ **현재 학습 라운드 = d9** (`run_name d9-qwen3-0.6b-lora`, epochs 3, output `models/lora/d9-qwen3-0.6b`).
- 🟡 **배포본은 아직 c2v13 Q8_0**(구 3-way). 앱 구스키마 폴백으로 호환 중. d-시리즈 통과 후 교체.

**버전 관리**: 학습 라운드 = `dN` 시리즈(현재 d9), 앱 = `versionName` (현재 `0.1.0`, `android/app/build.gradle`). 라운드 올릴 때 config 두 줄 + 데이터 커밋 동반.

**다음 할 일**
1. **d9 학습**: `git push origin main` → Kaggle/Colab 학습.
2. **d9 평가**: merge → `eval_model.py`(golden 50, 플랫 채점) → **Q8_0 양자화** → 폰 배포(§10).
3. **데이터 보강**: `is_schedule=false` 다양성(거래·광고·공고·남의 일정·location 오추출)을 `data/raw/` 실풀에서 추가 라벨링.
4. **앱 재빌드**: 카드 UI 변경 반영 Android Studio 재빌드 → APK 설치.

---

## 13. 트러블슈팅

| 증상 | 원인 / 해결 |
|------|------------|
| 배포 후 검출 안 됨 | force-stop/재설치 후 **앱 미실행(stopped)** → 브로드캐스트 차단. **앱 한 번 열기.** logcat `MessagePipeline: onMessage` 확인. |
| 카톡만 검출 안 됨 | 자가전송이면 정상(알림 없음). 실수신 + 그 방 닫아둔 상태여야. |
| 점수가 낮아 보임 | 결합 메트릭은 과발화 1건이 title/time/loc 동반 0처리 → 디커플링 지표(TP 추출력)로 확인. |
| Ollama 출력 빈손 | MX150 2GB/Vulkan 이슈. CPU 강제 또는 스킵. 모델은 fp16 eval로 검증. |
| `ollama create` "invalid model name" | Modelfile FROM이 상대경로 → 절대경로로. |
| 한글 깨짐(PowerShell/cp1252) | `PYTHONUTF8=1`. |
| Colab 학습물 증발 | 세션 종료 시 `/content/` 삭제. 끝나면 즉시 lora zip 다운로드. |
| 빌드 `Unable to delete directory ...dataBindingGenBaseClasses` (Defender ↔ Gradle 경합) | ① `gradlew --stop` + java 프로세스 kill ② 막힌 `app/build/generated/...out` 선제 삭제 ③ `gradlew :app:assembleDebug --no-daemon --no-watch-fs`. 근본해결 `Add-MpPreference -ExclusionPath D:\calenda`(관리자). |

---

## 14. 사용자 정보

- 이름: Soo / 변수룡 (`sooryong.byun@gmail.com` — 앱·git·캘린더·피드백 수신 통일). 한국어 대화 선호, 기술 용어 영어 OK. 질문·승인 최소화하고 합리적 기본값으로 자율 진행 선호.
- 머신: Windows 11, MX150 2GB. 폰: SM-S936N(무선 adb — 가끔 끊김, 무선 디버깅 재토글).
- 저장소: `D:\calenda` (GitHub `sooryong/Calenda`).

---

## 15. 모르는 게 있으면

- 출력 스키마: `prompts/schema.md` · 분류 기준: `prompts/schedule_criterion.md`
- 프롬프트 본문: `prompts/{planner,generator,evaluator}.md`
- 환경 설정 트러블슈팅: `SETUP.md`
