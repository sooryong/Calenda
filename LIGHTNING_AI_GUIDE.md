# Lightning AI & Hugging Face Sync Guide

이 가이드는 로컬 리소스를 쓰지 않고 클라우드(Lightning AI)에서 모델을 학습시키고, Hugging Face를 통해 데이터셋과 모델을 동기화하는 방법을 설명합니다.

---

## 1. Hugging Face 준비 (토큰 발급)
1. [Hugging Face Settings -> Access Tokens](https://huggingface.co/settings/tokens)로 이동합니다.
2. **`Write` 권한**을 가진 토큰(Token)을 하나 생성하여 복사해 둡니다.

---

## 2. 로컬에서 Hugging Face로 데이터셋 업로드

로컬 터미널에서 다음 명령어를 실행하여 데이터셋을 업로드합니다.

```powershell
# 1. 라이브러리 설치
pip install huggingface_hub datasets

# 2. Hugging Face 로그인 (발급받은 Write 토큰 입력)
huggingface-cli login

# 3. 로컬 data/ 폴더 전체를 업로드
# (your-username을 본인의 Hugging Face ID로 변경하세요)
huggingface-cli upload your-username/calenda-dataset ./data --repo-type dataset
```

---

## 3. Lightning AI 설정 및 학습 진행

1. [Lightning AI](https://lightning.ai/) 가입 후 **Blank Studio**를 생성합니다.
2. 우측 상단에서 **T4 GPU**로 전환합니다 (학습할 때만 켜서 크레딧 절약).
3. Studio 터미널에서 아래 명령어를 차례로 실행합니다.

```bash
# 1. 프로젝트 코드 가져오기 (Git 클론 또는 직접 파일 업로드)
git clone https://github.com/your-username/calenda.git
cd calenda

# 2. 의존성 패키지 설치
pip install -e .
pip install huggingface_hub

# 3. Hugging Face 로그인 (Write 토큰 입력)
huggingface-cli login

# 4. Hugging Face에서 데이터셋 다운로드
huggingface-cli download your-username/calenda-dataset --local-dir ./data --repo-type dataset

# 5. 모델 학습 시작
python scripts/train_lora.py --config configs/train.yaml
```

---

## 4. 학습 완료 후 모델 결과 저장 (Hugging Face)

학습이 끝난 후, 결과물(`models/lora/`)을 Hugging Face에 업로드하여 저장해 둡니다.

```bash
# models/lora/r11-qwen 폴더를 Hugging Face 모델 저장소에 업로드
huggingface-cli upload your-username/calenda-lora ./models/lora/r11-qwen --repo-type model
```

---

## 💡 크레딧 절약 팁
* 학습이나 코딩이 끝나면 반드시 화면 우측 상단의 **[Stop Studio]** 버튼을 눌러 인스턴스를 중지해야 크레딧 차감이 멈춥니다.
* 중지해도 작업하던 파일과 환경 설정은 다음번에 다시 켤 때 그대로 유지됩니다.
