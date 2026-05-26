# 개발 환경 구축 가이드 (Windows)

이 문서를 따라 한 번 세팅하면 데이터 생성 → 학습 → 양자화까지 진행할 수 있다.

---

## 0. 사전 준비

다음이 설치되어 있어야 한다.

- **Python 3.10~3.14** (현재 사용자 머신은 3.14)
  - 확인: `python --version`
  - 데이터 생성·평가는 3.14에서 잘 동작
  - 학습 단계에서 PyTorch wheel을 못 찾으면 그때 Python 3.11 별도 설치 (학습용 venv를 분리)
- **Git** (필수는 아니지만 권장): https://git-scm.com/
- **CUDA Toolkit** (GPU 학습 시): 12.1 이상 권장. 없어도 데이터 생성·평가까지는 진행 가능.

---

## 1. API 키 입력

`.env` 파일을 열어 `ANTHROPIC_API_KEY=` 뒤에 본인 키를 붙여넣는다.

```
ANTHROPIC_API_KEY=sk-ant-api03-...실제키...
```

키 발급: https://console.anthropic.com/ → API Keys

> ℹ️ `.env`는 `.gitignore`에 등록되어 있어 git에 올라가지 않음. 안전.

---

## 2. 가상환경 생성

PowerShell에서 프로젝트 폴더로 이동:

```powershell
cd D:\calendar-agent
```

가상환경 생성 + 활성화:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 실행 정책 오류가 나면 한 번만:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

프롬프트 앞에 `(.venv)` 가 보이면 성공.

확인:
```powershell
python --version
where python    # .venv 안의 python.exe를 가리켜야 함
```

---

## 3. 의존성 설치 — 단계별

### 3-1. 데이터 생성·평가용 (가벼움, 먼저 설치)

```powershell
pip install --upgrade pip
pip install -e .
```

설치 확인:
```powershell
python -c "import anthropic, orjson, pandas, tqdm, tenacity; print('OK')"
```

이 단계까지면 **데이터 생성(Planner/Generator) 및 데이터 QA**가 가능하다.

### 3-2. 학습 라이브러리 (무거움, GPU 학습 직전에)

```powershell
pip install -e .[train]
```

> PyTorch가 CPU 버전으로 깔리는 경우가 있다. GPU가 있다면 다음 한 줄로 CUDA 빌드 명시:
> ```powershell
> pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121
> ```

설치 확인:
```powershell
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```

### 3-3. UI (Streamlit, 데이터 검수할 때)

```powershell
pip install -e .[ui]
```

---

## 4. Windows-특이 주의사항

### 4-1. bitsandbytes (4-bit QLoRA용)

`pyproject.toml`에서 Windows는 자동 설치 대상에서 제외했다 (공식 wheel이 Linux 위주).

0.5B 모델은 4-bit 없이도 일반 GPU에서 fit하므로 **일단 안 깔아도 OK**.

필요해질 때만 별도 설치:
```powershell
pip install bitsandbytes
```
설치 후 import 에러가 나면 `bitsandbytes-windows` 포크를 시도하거나, `configs/train.yaml`에서 `load_in_4bit: false`로 두고 진행.

### 4-2. 한글 경로

`D:\calendar-agent`는 영어 경로라 문제 없음. 다만 `HF_HOME=D:/calendar-agent/.cache/hf`처럼 슬래시 방향 주의 (Python은 `/` 권장, Windows도 인식함).

### 4-3. llama.cpp 빌드 (양자화 단계)

양자화 단계에 가서야 필요. PowerShell에서:

```powershell
cd D:\
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DLLAMA_CUDA=OFF    # 양자화만 쓰면 CUDA 불필요
cmake --build build --config Release
pip install -r requirements.txt
```

`scripts/quantize.sh`는 git-bash 또는 WSL에서 실행. PowerShell에서는 명령들을 풀어서 직접 실행하거나, 동등한 .ps1 스크립트를 만들면 됨.

---

## 5. 스모크 테스트

가상환경 + `.env` 키 입력이 끝났다면, Planner를 아주 작게 한 번 돌려보자.

`scripts/plan.py`는 기본적으로 ~5000건 시나리오를 만드므로, 빠른 검증을 위해 임시로 작은 규모 테스트:

```powershell
# (선택) 임시 미니 테스트: 100건짜리 명세서로 출력 형식만 확인
python scripts/plan.py --out data/raw/plan_smoke.json
type data\raw\plan_smoke.json   # 결과 살펴보기
```

정상이면 시나리오 객체 30~50개가 들어있는 JSON 배열이 보인다.

문제 없으면:
```powershell
# 미니 데이터 생성 (시나리오의 count를 줄여서 ~100건만)
# 실제로는 scripts/generate.py에 --limit 등의 옵션을 추가하면 좋음 (TODO)
python scripts/generate.py --plan data/raw/plan_smoke.json --out data/raw/smoke.jsonl --workers 2
```

생성된 `smoke.jsonl`을 열어 메시지/gold 모양 확인.

---

## 6. 트러블슈팅

| 증상 | 해결 |
|------|------|
| `Activate.ps1 실행 안 됨` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ANTHROPIC_API_KEY가 .env에 없습니다` | `.env` 파일에 키 입력 후 PowerShell 재시작 |
| `torch CUDA: False` (GPU 있는데) | 3-2의 CUDA 빌드 명시 명령으로 재설치 |
| HuggingFace 다운로드 느림 | `HF_TOKEN` 발급 후 `.env`에 넣으면 빨라짐 (rate-limit 완화) |
| 한글 깨짐 | PowerShell: `chcp 65001` 로 UTF-8 모드 |

---

## 다음 단계

세팅 끝나면:
1. `data/eval/golden.jsonl` 골든 평가셋 50~100건 수동 작성 (가장 중요)
2. 본격 데이터 생성 (`plan.py` → `generate.py` → `evaluate_data.py`)
3. LoRA 학습
4. 평가 → 폐루프
5. 양자화 → 안드로이드 디바이스 테스트
