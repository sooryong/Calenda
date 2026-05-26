# Calendar Agent — 프로젝트 가이드 (Claude Code용)

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는 프로젝트 컨텍스트다.
> **사용자에게 코드를 짜주기 전에 반드시 이 파일과 `prompts/schema.md`를 먼저 읽어라.**
> 새 세션에서 막막하면 `HANDOFF.md`를 먼저 보면 지금 무엇을 해야 하는지 정확히 적혀 있다.

---

## 1. 프로젝트 목표

안드로이드 폰에서 SMS / 카카오톡 / Gmail로 들어오는 메시지에서 **일정을 자동 추출해 Google Calendar에 등록**하는 에이전트.

핵심 제약: **온디바이스 LLM, ~400MB**. Qwen2.5-0.5B-Instruct(또는 HyperCLOVA X SEED 0.5B)를 LoRA 파인튜닝 + GGUF INT4 양자화로 폰에 올린다.

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
calendar-agent/
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
│   ├── model_qwen.yaml       ← Qwen2.5-0.5B (1차)
│   ├── model_hyperclova.yaml ← HyperCLOVA X SEED 0.5B (비교용)
│   ├── lora.yaml             ← r=16, alpha=32
│   └── train.yaml            ← 하이퍼파라미터 전체
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
├── notebooks/, logs/, android/   (안드로이드 앱은 추후)
```

---

## 4. 출력 JSON 스키마 (절대 중요)

전체 시스템이 이 스키마를 공유한다. `prompts/schema.md`에 상세. 요약:

```json
{
  "has_schedule": true,
  "events": [
    {
      "title": "팀 주간 회의",
      "start": "2026-05-26T15:00:00+09:00",
      "end":   "2026-05-26T16:00:00+09:00",
      "all_day": false,
      "location": "회사 3층 회의실",
      "attendees": ["김부장"],
      "description": null,
      "recurrence": null,
      "confidence": 0.95
    }
  ]
}
```

### 입력 포맷 (학습/추론)
모델은 다음 user 메시지를 받는다:
```
<채널: KakaoTalk>
<수신시각: 2026-05-25T14:30:00+09:00>
<발신자: 김부장>
<메시지>
내일 3시에 회사 3층에서 주간회의 잡았습니다.
</메시지>
```
→ 모델은 위 스키마 JSON만 출력 (코드펜스 없는 순수 JSON).

**수신시각이 입력에 포함된다.** 상대 시간("내일")을 이 기준으로 절대 시각으로 변환해야 한다. 시간대 명시 안 되면 +09:00.

---

## 5. 규약 / 컨벤션

### 프롬프트 수정 시
- `prompts/*.md`의 섹션 헤더와 ` ``` ` 펜스 구조는 **정규식으로 파싱**한다 (각 `scripts/*.py` 상단 RE 참조). 헤더 텍스트나 펜스 위치를 바꾸면 스크립트가 깨진다.
- Generator 프롬프트의 `### 예시 N:` 블록도 정규식으로 회전 사용된다.

### 데이터 형식
- 모든 데이터는 **JSONL** (한 줄에 dict 하나, `orjson` 사용).
- 페어 필드: `scenario_id`, `received_at`, `channel`, `sender`, `language`, `message`, `gold`.
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

1차 후보: **Qwen/Qwen2.5-0.5B-Instruct** (`configs/model_qwen.yaml`)
- 다국어 안정, 한국어 양호, 토크나이저 효율 OK
- LLaMA-like 구조라 LoRA target_modules 표준

비교 후보: **naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B** (`configs/model_hyperclova.yaml`)
- 네이버, 한국어 네이티브
- `trust_remote_code=true` 필요할 수 있음 (모델 카드 확인)
- 라이선스 사용 전 확인 필수

모델 교체는 `configs/train.yaml`의 `model_config:` 한 줄만 바꾸면 됨.

---

## 7. 환경

- **Python 3.10~3.14**: 데이터 생성·평가 단계는 3.14에서도 잘 동작.
  - **학습 단계**(`pip install -e .[train]`)에서 PyTorch/bitsandbytes wheel 못 찾으면 Python 3.11을 별도 설치 후 그쪽 venv로 학습만 수행.
- OS: Windows 11 (D:\calendar-agent에 설치). 학습 시 CUDA GPU 권장.
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

# 학습 → merge → 평가 → 양자화
python scripts/train_lora.py  --config configs/train.yaml
python scripts/merge_lora.py  --base Qwen/Qwen2.5-0.5B-Instruct --lora models/lora/v1 --out models/merged/v1
python scripts/eval_model.py  --model models/merged/v1 --eval data/eval/golden.jsonl --out logs/eval_v1.json
bash   scripts/quantize.sh    models/merged/v1 models/gguf/v1

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

상세는 `HANDOFF.md` 참조. 요약:
- ✅ 스켈레톤(폴더/스크립트/프롬프트/configs) 완성
- ✅ `.env`에 API 키 입력됨
- 🔧 Windows venv 구축 중 (Python 3.14 사용, pyproject.toml 버전 제약 완화함)
- ⏳ Planner 첫 실행
- ⏳ Generator로 5K 페어 생성
- ⏳ 골든 평가셋 50~100건 **수동 작성** (가장 중요한 다음 작업)

---

## 11. 모르는 게 있으면

- 출력 스키마: `prompts/schema.md`
- 프롬프트 본문: `prompts/{planner,generator,evaluator}.md`
- 환경 설정 트러블슈팅: `SETUP.md`
- 지금 당장 할 일: `HANDOFF.md`
