# HANDOFF — 지금 당장 무엇을 할 것인가

> Claude Code 세션이 시작될 때 가장 먼저 읽어야 할 파일.
> 전체 프로젝트 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md` 참조.

## 핸드오프 사유

이 프로젝트는 원래 Cowork 탭에서 시작됐다. 데이터 생성 파이프라인(Planner→Generator→Evaluator)을 그쪽 샌드박스에서 돌리려 했지만, **Cowork 샌드박스가 외부 API 호출(api.anthropic.com 포함)을 차단**한다. 그래서 사용자의 실제 Windows 머신에서 명령을 직접 실행할 수 있는 **Claude Code 탭으로 이관**했다.

여기서 너는 PowerShell에 직접 접근할 수 있으므로:
- Python 설치/관리
- venv 생성·재생성
- pip 패키지 설치
- `scripts/*.py` 실행 (Anthropic API 호출 포함)
가 전부 가능하다.

---

## 1. 현재 상태 (이미 끝난 것)

- ✅ 전체 디렉토리 구조 (`data/`, `prompts/`, `scripts/`, `configs/`, `models/`, `ui/`, `notebooks/`, `logs/`, `android/`)
- ✅ `pyproject.toml` — 데이터/학습/UI 의존성을 extras로 분리
- ✅ `.env` 파일에 `ANTHROPIC_API_KEY` 입력됨 (값 검증은 아직 못함 — Cowork 샌드박스에서 막혀서)
- ✅ `prompts/schema.md` — 출력 JSON 스키마 정의
- ✅ `prompts/planner.md`, `prompts/generator.md`, `prompts/evaluator.md` — 프롬프트 초안 작성됨
- ✅ `scripts/` — 7개 파이프라인 스크립트 + `_common.py` (syntax 검증 완료)
- ✅ `configs/` — model_qwen, model_hyperclova, lora, train 4개 YAML
- ✅ `ui/streamlit_app.py` — 데이터 검수 UI 스켈레톤

## 2. 현재 막힌 지점 (Python 버전)

사용자 머신에는 **Python 3.14**가 깔려 있다. 원래 `pyproject.toml`은 `>=3.10,<3.13`을 요구해서 의존성 설치가 스킵됐다. **이미 `pyproject.toml`을 `>=3.10,<3.15`로 완화**했으므로 **3.14 그대로 진행하면 된다**. 학습 단계에서 PyTorch wheel 문제가 생기면 그때 가서 3.11을 추가 설치한다(데이터 생성·평가는 3.14에서 잘 동작).

## 3. 당장 할 일 — 정확한 순서

### Step 1. venv 재생성 (3.14 그대로 사용)

```powershell
cd D:\calendar-agent

# 기존(반쪽만 깔린) venv 제거
Remove-Item -Recurse -Force .\.venv

# 3.14로 venv 만들기 (기본 python 사용)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 버전 확인 (3.14.x)
python --version
```

### Step 2. 의존성 설치 (데이터 생성용만, 가벼움)

```powershell
python -m pip install --upgrade pip
pip install -e .

# 임포트 확인
python -c "import anthropic, orjson, yaml, tenacity, tqdm, rapidfuzz; print('OK')"
```

- 3.14에서 wheel 못 찾는 패키지가 나오면 메시지를 사용자에게 보고하고 의논. 보통 `pip install <패키지>==<버전>`으로 살짝 낮춰주거나, `--pre` 옵션으로 해결됨.
- 학습 라이브러리(`pip install -e .[train]`)는 지금 깔지 마라. 용량 크고 GPU 필요. **학습 단계에 들어갈 때** 3.14에서 torch wheel 있는지 확인하고, 없으면 그때 Python 3.11 별도 설치 후 학습용 venv를 따로 만든다.

### Step 3. Planner 첫 실행 (Anthropic API 호출 첫 검증)

```powershell
python scripts/plan.py --out data/raw/plan_v1.json
```

- 약 30초~1분
- 콘솔에 `[plan] 시나리오 N개, 합산 count=~5000 → data/raw/plan_v1.json` 같은 메시지
- 결과: 시나리오 30~50개의 JSON 배열

### Step 4. 결과 검토

```powershell
# 처음 몇 항목 보기
python -c "import json; d=json.load(open('data/raw/plan_v1.json',encoding='utf-8')); print(f'총 {len(d)}개 시나리오, count 합={sum(s.get(\"count\",0) for s in d)}'); print(json.dumps(d[:3], ensure_ascii=False, indent=2))"
```

검토 포인트:
- 시나리오 개수가 30~50 사이인가?
- count 합이 4000~6000 사이인가?
- **`edge_case: "no_schedule"`**인 시나리오의 count 합이 전체의 25% 이상인가? (중요)
- 채널(sms/kakao/gmail) 비중이 비슷한가?
- 언어 비중 (ko 60% / en 25% / mixed_ko_en 15%) 근사한가?

비중이 틀어지면 `prompts/planner.md`의 system prompt 차원 정의를 조정하고 재실행한다.

---

## 4. Step 4까지 성공한 다음 — 다음 절차

### A. 미니 Generator 실행 (200건 정도로 모양 확인)

`scripts/generate.py`는 plan의 모든 시나리오를 처리한다. 미니 테스트를 위해 plan 파일을 임시로 잘라서 쓴다:

```powershell
# plan을 작게 잘라 미니 plan 만들기 (count도 작게 낮추기)
python -c "
import json
d = json.load(open('data/raw/plan_v1.json', encoding='utf-8'))
mini = []
for s in d[:6]:
    s = dict(s)
    s['count'] = max(5, s.get('count', 0) // 10)
    mini.append(s)
json.dump(mini, open('data/raw/plan_smoke.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'mini plan: {len(mini)} scenarios, total {sum(s[\"count\"] for s in mini)}')
"

python scripts/generate.py --plan data/raw/plan_smoke.json --out data/raw/smoke.jsonl --workers 2
```

생성된 `data/raw/smoke.jsonl`을 열어서 (a) 메시지가 자연스러운가, (b) gold JSON이 스키마를 따르는가, (c) `has_schedule=false` 케이스가 잘 섞여 있는가 확인.

### B. 데이터 QA 스모크

```powershell
python scripts/evaluate_data.py --in data/raw/smoke.jsonl --out data/processed/smoke.jsonl
```

- accept / fix / reject 비율 출력됨
- 보통 reject가 5~15% 정도면 정상
- 너무 높으면 (>30%) Generator 프롬프트나 few-shot이 약함 → 보강

### C. 골든 평가셋 50~100건 수동 작성 (가장 중요)

`data/eval/golden.jsonl` 작성. 이게 학습 효과 측정의 유일한 기준이라 본 학습 들어가기 전 반드시 확보.

작성 방식:
- 사용자가 직접 또는 사용자 + Claude Code가 협업으로
- 다양한 채널·언어·에지케이스 모두 커버 (특히 `no_schedule`, `multi_event`, `cancellation`, `confirmation_request`)
- 형식은 `data/raw/smoke.jsonl`과 동일 (scenario_id는 `golden_NNN` 같은 자체 ID 부여)
- 각 페어는 **사용자가 정답에 대한 자신감 100%인 것만** 채택. 모호한 건 빼라.

이 단계는 작업이 많으므로 Claude Code가 사용자에게 5~10건씩 제안하고 사용자가 검토/수정/확정하는 방식이 효율적.

### D. 본 데이터 생성 (5K 풀 규모)

골든셋 준비됐다면:
```powershell
python scripts/generate.py --plan data/raw/plan_v1.json --out data/raw/v1.jsonl --workers 4
python scripts/evaluate_data.py --in data/raw/v1.jsonl --out data/processed/v1.jsonl
```

- 비용: Haiku로 ~5000건 생성 + 검증, 보통 $1~3
- 시간: workers=4 기준 20~40분

### E. 학습 환경 추가 설치

이 시점에 학습 라이브러리:
```powershell
pip install -e .[train]
# GPU 있다면 CUDA 빌드 명시
pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121
```

이후 train_lora → merge_lora → eval_model → quantize 순서. `CLAUDE.md` §8 참조.

---

## 5. 너(Claude Code)의 행동 원칙

- **사용자 머신에서 명령 실행하기 전에 항상 무엇을 할지 한 줄 설명하고 허락 받아라.** 특히 `Remove-Item`, `pip install` 같은 변경 작업.
- API 호출에는 비용이 든다. 새 모델/큰 prompt 실험할 땐 사용자에게 먼저 알려라.
- 프롬프트(`prompts/*.md`)를 수정할 땐 정규식 파싱 호환성을 깨지 마라 — 각 `scripts/*.py` 상단의 `RE` 패턴들이 헤더와 코드펜스 구조에 의존한다.
- 모델 출력은 항상 `_common.safe_json_loads()`로 파싱하라 (직접 `json.loads` 금지 — 코드펜스 포함된 경우 깨짐).
- 데이터 파일은 항상 JSONL + UTF-8. CSV 쓰지 마라.
- 비용·시간이 큰 작업(전체 5K 생성, 학습) 시작 전에는 미니 스모크부터 돌려서 형식·결과를 확인하라.

---

## 6. 트러블슈팅 메모

| 증상 | 원인 / 해결 |
|------|------------|
| `pip install -e .`가 "requires a different Python" | Python 버전 안 맞음. 3.11 venv인지 `python --version`으로 확인 |
| `ANTHROPIC_API_KEY가 .env에 없습니다` | venv 활성화 후 `cd D:\calendar-agent`인지 확인 (load_dotenv는 cwd의 .env 읽음) |
| `Anthropic.AuthenticationError 401` | 콘솔에서 키 재발급 후 `.env` 교체 |
| Planner 출력 JSON 파싱 실패 | `prompts/planner.md`의 system에 "JSON 배열만 출력" 강조 확인. `_common.safe_json_loads` 사용했는지 확인. |
| `bitsandbytes` import 에러 (Windows) | `configs/train.yaml`의 `load_in_4bit: false`로 두고 진행. 0.5B는 4-bit 없이도 학습 가능. |
| 한글 깨짐 (PowerShell) | `chcp 65001` 로 UTF-8 모드. 또는 `[Console]::OutputEncoding = [Text.Encoding]::UTF8` |

---

## 7. 사용자 정보

- 이름: Soo
- 머신: Windows 11
- 작업 폴더: `D:\calendar-agent` (OneDrive 바깥, ML 작업 친화)
- 한국어로 대화 선호. 기술 용어는 영어 그대로 OK.
- Anthropic 콘솔에 약 USD 19 크레딧 보유 (한 라운드는 충분)

세션 첫 메시지로 사용자에게 **"방금 Cowork 탭에서 이관했습니다. CLAUDE.md와 HANDOFF.md를 읽었고, 현재 Python 3.11 설치 → venv 재구성 → Planner 첫 실행이 다음 차례입니다. 진행할까요?"** 정도로 시작하면 매끄럽다.
