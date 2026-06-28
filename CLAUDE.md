# Calendar Agent — 프로젝트 가이드 (Claude Code용)

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는 프로젝트 컨텍스트다.
> **사용자에게 코드를 짜주기 전에 반드시 이 파일과 `prompts/schema.md`를 먼저 읽어라.**
> 새 세션에서 막막하면 `HANDOFF.md`를 먼저 보면 지금 무엇을 해야 하는지 정확히 적혀 있다.

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

---

## 3. 디렉토리 구조

```
calenda/
├── CLAUDE.md             ← 이 파일
├── HANDOFF.md            ← 지금 당장 할 일 (세션 시작 시 같이 봐라)
├── README.md             ← 사람용 개요
├── SETUP.md              ← 환경 구축 가이드
├── pyproject.toml        ← Python 3.10~3.14 지원 (학습 단계는 3.11 권장)
├── .env                  ← ANTHROPIC_API_KEY (gitignore)
├── .env.example
│
├── prompts/              ← ★ 모델 호출 프롬프트 (수정 시 신중)
│   ├── schema.md         ← 단일 출력 JSON 스키마 (반드시 먼저 읽기)
│   ├── planner.md        ← Planner system/user 프롬프트
│   ├── generator.md      ← Generator + few-shot 예시 7개
│   └── evaluator.md      ← 데이터 QA + 모델 Judge 프롬프트
│
├── scripts/
│   ├── _common.py        ← Anthropic 호출, JSONL I/O, JSON 추출
│   ├── plan.py           ← Planner 실행
│   ├── generate.py       ← Generator (병렬 호출)
│   ├── evaluate_data.py  ← 데이터 QA
│   ├── train_lora.py     ← SFTTrainer + PEFT LoRA
│   ├── merge_lora.py     ← LoRA → merged FP16
│   ├── eval_model.py     ← 골든셋 평가
│   └── quantize.sh       ← llama.cpp 양자화
│
├── configs/
│   ├── model_qwen3_0_6b.yaml  ← Qwen3-0.6B (단일 베이스)
│   ├── lora.yaml             ← r=16, alpha=32
│   └── train_qwen3_0_6b.yaml ← 하이퍼파라미터 (completion-only ON)
│
├── data/
│   ├── raw/              ← Generator 원본 출력
│   ├── processed/        ← QA 통과한 학습용
│   ├── eval/             ← ★ 골든 평가셋 (수동 작성)
│   └── failures/         ← 실패 케이스 (폐루프 입력)
│
├── models/
│   ├── lora/             ← LoRA 어댑터
│   ├── merged/           ← merged FP16
│   └── gguf/             ← Q4_K_M 등
│
├── ui/streamlit_app.py   ← 데이터 검수 + 에러 분석 (Streamlit)
├── notebooks/            ← calendar_colab.ipynb(Colab L4 학습) / calendar_quantize.ipynb(로컬 양자화)
├── logs/                 ← 학습/평가 로그
└── android/              ← 온디바이스 앱 (SMS/카톡 수집 + GGUF 추론 + DateResolver)
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
- QA 통과 페어는 `_qa` 필드 추가, 평가 실패 케이스는 `_pred` / `_scores` / `_reason` 추가.

### 모델 호출
- 모든 호출은 `scripts/_common.py`의 `call_claude()`를 거친다 — 재시도/지수백오프 내장.
- 기본 teacher 모델:
  - Planner: `claude-sonnet-4-6`
  - Generator: `claude-haiku-4-5-20251001`
  - Data QA: `claude-haiku-4-5-20251001`
  - Model Judge: `claude-sonnet-4-6`

### 라이선스 / 보안
- `.env`는 절대 커밋 금지 (`.gitignore` 등록됨).
- 모델/대용량 데이터도 git 제외. `data/eval/golden.jsonl`만 추적 대상(수동 골든셋).

---

## 6. 베이스 모델 / 토크나이저

**단일 베이스: Qwen/Qwen3-0.6B** (`configs/model_qwen3_0_6b.yaml`)
- 한국어 양호, 토크나이저 효율 OK, LLaMA-like 구조라 LoRA target_modules 표준(q/k/v/o/gate/up/down_proj)
- thinking 모델이나 SFT gold가 순수 JSON이라 학습으로 비-thinking 고정. 추론은 빈 `<think></think>` 프리필.
- 폰 예산권 ~800MB(Q8까지). 배포 양자화는 Q8_0 고정(Q4_K_M은 회귀).

(이전 Qwen2.5-0.5B / HyperCLOVA 라인은 폐기·삭제됨. 모델은 Qwen3-0.6B로 통일.)

---

## 7. 환경

- **Python 3.10~3.14**: 데이터 생성·평가 단계는 3.14에서도 잘 동작.
  - **학습 단계**(`pip install -e .[train]`)에서 PyTorch/bitsandbytes wheel 못 찾으면 Python 3.11을 별도 설치 후 그쪽 venv로 학습만 수행.
- OS: Windows 11 (D:\calenda에 설치). 학습 시 CUDA GPU 권장.
- 의존성은 단계별 분리:
  - `pip install -e .` — 데이터 생성·평가 (가벼움)
  - `pip install -e .[train]` — 학습 라이브러리 (torch, peft, trl, transformers)
  - `pip install -e .[ui]` — Streamlit
- 양자화: `llama.cpp` 별도 클론 + 빌드 (`scripts/quantize.sh` 참고)

---

## 8. 자주 쓰는 명령

```powershell
# venv 활성화
.\.venv\Scripts\Activate.ps1

# 데이터 파이프라인 (한 라운드)
python scripts/plan.py        --out data/raw/plan_v1.json
python scripts/generate.py    --plan data/raw/plan_v1.json --out data/raw/v1.jsonl --workers 4
python scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl

# 학습 → merge → 평가 → 양자화 (학습은 Colab L4, merge/eval/quantize는 로컬)
python scripts/train_lora.py  --config configs/train_qwen3_0_6b.yaml
python scripts/merge_lora.py  --base Qwen/Qwen3-0.6B --lora models/lora/c2-qwen3-0.6b --out models/merged/c2-qwen3-0.6b
python scripts/eval_model.py  --model models/merged/c2-qwen3-0.6b --eval data/eval/golden.jsonl --out logs/eval_c2-qwen3-0.6b.json --model_config configs/model_qwen3_0_6b.yaml
bash   scripts/quantize.sh    models/merged/c2-qwen3-0.6b models/gguf/c2-qwen3-0.6b

# 폐루프: 실패셋으로 다음 라운드 시나리오 생성
python scripts/plan.py --failures data/failures/round_latest.jsonl --out data/raw/plan_v2.json

# UI
streamlit run ui/streamlit_app.py
```

---

## 9. 폐루프 (Active Learning)

`scripts/eval_model.py`가 점수 낮은 샘플을 `data/failures/round_latest.jsonl`에 자동 저장한다.
다음 라운드 Planner를 `--failures` 옵션으로 호출하면 약점 보강 시나리오 위주로 생성한다.
보통 3~5라운드면 plateau에 도달한다.

---

## 10. 현재 개발 단계

상세·다음 할 일은 `HANDOFF.md`, 과거 라운드 이력은 `ARCHIVE.md` 참조. 요약 (2026-06-29):
- ✅ **방향 전환**: 합성 라운드(r11~r34·c1/c2/c9 계열) 전부 폐기 → **실제 SMS/카톡/Gmail 수집 데이터**로 재구축. `data/raw/`에 실메시지 풀.
- ✅ **플랫 스키마 마이그레이션 완료**: `is_schedule`(bool) + `title/date/time/end_time/location/description` 단일 이벤트. `prompts/schema.md`·`schedule_criterion.md`(yes/no 2-way)·`eval_model.py`·앱(`ScheduleExtractor`/`DateResolver`) 전부 플랫.
- ✅ **extract-resolve 유지**: 모델=추출, resolver=계산. `_common`↔`DateResolver` 미러. 멀티턴 `build_user_block` 공용.
- ⏳ **현재: d8 학습 단계.** `configs/train_qwen3_0_6b.yaml` run_name=`d8-qwen3-0.6b-lora`, epochs=3. `train.jsonl` **371건**(is_schedule true/false 혼합) · `golden.jsonl` **50건**. → push → Kaggle/Colab 학습 → merge → eval → Q8_0 양자화.
- 🟡 **배포본은 아직 c2v13 Q8_0**(구 3-way). 앱이 구스키마 폴백으로 호환 중. d8 학습·평가 통과 후 교체 예정.
- ✅ **앱 카드 UI 개편**: 카드 탭 → 원본 메시지 앱 열기(SMS는 발신자 대화방 딥링크), 발신자 필수 표시 + 장소·설명, 버튼 [삭제]·[등록하기]/[등록취소]. (구 [소스]·[캘린더] 버튼·카드탭→편집 폐지)

---

## 11. 모르는 게 있으면

- 출력 스키마: `prompts/schema.md`
- 프롬프트 본문: `prompts/{planner,generator,evaluator}.md`
- 환경 설정 트러블슈팅: `SETUP.md`
- 지금 당장 할 일: `HANDOFF.md`
- 과거 라운드 이력(r11~r34·c1/c2/c9·d5~ 진단·설계): `ARCHIVE.md`
