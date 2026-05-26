# Calendar Agent — On-Device Schedule Extraction

안드로이드 폰에서 SMS / 카카오톡 / Gmail로 들어오는 메시지에서 일정을 자동 추출해 Google Calendar에 등록하는 에이전트.

베이스 LLM(Qwen2.5-0.5B-Instruct)에 LoRA 파인튜닝 + GGUF INT4 양자화를 적용해 ~400MB 크기로 안드로이드 온디바이스 실행을 목표로 한다.

## 학습 파이프라인 아키텍처

```
┌──────────┐   시나리오    ┌───────────┐   (input, JSON)   ┌────────────┐
│ Planner  │ ────────────> │ Generator │ ────────────────> │ Evaluator  │
│ (Sonnet) │               │  (Haiku)  │                   │ (Haiku+규칙) │
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

- **Planner**: 어떤 시나리오를 몇 건씩 생성할지 설계 (Claude Sonnet)
- **Generator**: 실제 (메시지, gold JSON) 페어 생성 (Claude Haiku)
- **Evaluator**: 합성 데이터 품질 검증 + 학습된 모델 평가
- **Harness**: LoRA 학습 → merge → GGUF 양자화 → 평가 → 배포 오케스트레이션

## 디렉토리

```
calendar-agent/
├── data/         # raw 합성 / processed / eval(골든) / failures
├── prompts/      # planner.md, generator.md, evaluator.md
├── scripts/      # plan, generate, evaluate_data, train_lora, merge_lora, eval_model, quantize
├── models/       # lora 어댑터, merged FP16, gguf 양자화 결과
├── configs/      # train.yaml, lora.yaml, model_*.yaml
├── ui/           # Streamlit 데이터 검수·에러 분석 UI
├── notebooks/    # 탐색용 ipynb
├── logs/         # 학습 로그
└── android/      # 안드로이드 앱 코드 (추후)
```

## 빠른 시작

```bash
# 1. 가상환경
python -m venv .venv
.venv\Scripts\activate

# 2. 의존성
pip install -e .

# 3. 환경변수
cp .env.example .env
# .env에 ANTHROPIC_API_KEY 입력

# 4. 데이터 생성 → 평가 → 학습 → 양자화
python scripts/plan.py        --out data/raw/plan_v1.json
python scripts/generate.py    --plan data/raw/plan_v1.json --out data/raw/v1.jsonl
python scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl
python scripts/train_lora.py  --config configs/train.yaml
python scripts/merge_lora.py  --lora models/lora/v1 --out models/merged/v1
python scripts/eval_model.py  --model models/merged/v1 --eval data/eval/golden.jsonl
bash   scripts/quantize.sh    models/merged/v1 models/gguf/v1
```

## 베이스 모델

- 1차: `Qwen/Qwen2.5-0.5B-Instruct`
- 비교 후보: `naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B`

## 라이선스

TBD
