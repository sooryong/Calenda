# HANDOFF — 지금 당장 무엇을 할 것인가

> 세션 시작 시 가장 먼저 읽는 파일. 전체 컨텍스트는 `CLAUDE.md`, 출력 스키마는 `prompts/schema.md`.
> (이전 "Cowork→Claude Code 이관" 단계는 종료됨. 데이터·학습·앱 모두 진행됨.)

---

## 1. 현재 상태 (2026-05-31)

- ✅ **데이터**: `data/processed/train.jsonl` 2245건(base 1775 + weekend 250 + cowork 100 + thread 120), `val.jsonl` 195, 골든 `data/eval/golden.jsonl` 51건. 모두 git 추적(force-add).
- ✅ **스키마**: extract-resolve로 마이그레이션 완료. 모델=표면형 추출(`date` 토큰 + `time`), 계산=resolver(`_common.resolve_when` ↔ 앱 `DateResolver`). 둘이 같은 표 공유.
- ✅ **멀티턴**: `<대화내역>` 블록 학습·평가·앱 배선 완료(`build_user_block` 공용).
- ✅ **최적 레시피 확정**(r3~r11 2×2 격자): **bf16 + base 2245**. fp16도 discipline 보강도 각각 ~4~5점 해침. Kaggle **T4x2 DDP(torchrun)**로 ~56분.
- ✅ **r11 = golden 0.905 / time_match 0.788** ← 배포본. merge → quantize 완료: `models/gguf/r11-qwen/r11-qwen.Q4_K_M.gguf` (380MB).
- ✅ 로컬 딥검증 통과: 토요일 "내일"→일요일 등 주말 횡단 정확.
- ✅ **Android 앱**: SMS BroadcastReceiver + 카톡 NotificationListener 수집, 새 스키마 파서, `DateResolver`, 멀티턴 `ConversationBuffer`까지 빌드 성공.

## 2. 당장 할 일 — 폰 배포 (사용자 진행)

1. **gguf 폰 임포트**: `models/gguf/r11-qwen/r11-qwen.Q4_K_M.gguf` → 앱이 찾는 슬롯명 `ModelStore.FILE_NAME = "calendar.Q4_K_M.gguf"`로 들어가야 함.
2. **앱 재빌드 (Android Studio)**: 이번 라운드는 **스키마가 바뀌었다**. 구앱 + 신모델이면 깨지므로 반드시 새로 빌드·설치. (빌드는 사용자가 Studio에서 — CLI gradle 금지.)
3. **온디바이스 검증**: 토요일에 "내일 오후 2시 ○○ 회의" → **일요일 14:00**로 잡히는지 확인.

## 3. 다음 라운드 (품질 보강) — plateau는 아직

- **location 오추출** (사람 이름이 장소로 샘, 예: "정원구 대표"→location "정원구"; `구`/`동` 행정구역 접미사 오인):
  - ✅ **A 적용됨**: resolver 가드 — location이 참석자 이름의 일부면 null. `_common._drop_personlike_location` + 앱 `DateResolver.dropPersonlikeLocation`(둘이 미러). 재빌드에 포함.
  - ⏳ **B (다음 라운드, 근본 교정)**: `구/동/읍/면`으로 끝나는 **사람 이름**이 attendees로 가고 location은 null이어야 하는 대조 케이스를 소량(~30~50건) 추가. 모델이 원인 자체를 학습 → 가드 의존 줄임.
- **음성 보강은 소량·다양만**: 대량 템플릿 음성/맨시각(gen_discipline)은 over-trigger 회귀를 부름 → 제거됨. 음성:양성 ~40% 균형 유지.
- 약점 케이스는 `scripts/eval_model.py`가 `data/failures/round_latest.jsonl`에 저장 → 다음 라운드 데이터 생성에 반영.

---

## 4. 학습 한 라운드 (Kaggle, 권장 경로)

`notebooks/calendar_kaggle.ipynb`를 위→아래 실행. 데이터가 repo에 포함돼 **clone만으로** 학습(별도 Kaggle 데이터셋 불필요).

- 정밀도/라운드는 `configs/train.yaml`(`output_dir`, `run_name`)에서 인식. 다음 라운드면 `r11`→`r12`로 두 곳만 올린다.
- T4 **2개** 선택 → cell이 `torchrun --nproc_per_node=2`로 DDP. (그냥 python+2GPU는 DataParallel이라 안 빠름.)
- **끝나면 즉시 zip 다운로드.** Kaggle 세션 정리가 `/kaggle/working`을 날린다(r8 2h 소실 전례). 또는 Save & Run All(Commit).
- 로컬에서 zip 받아 `models/lora/rN-qwen/`에 풀고 → `merge_lora.py` → `eval_model.py` → `quantize.sh`.
- fp16 대안 환경은 `colab_train.ipynb` + `configs/train_colab.yaml`. (단 fp16은 bf16보다 ~5점 낮음 — 품질 필요하면 Kaggle bf16.)

명령 요약은 `CLAUDE.md` §8.

---

## 5. 행동 원칙 / 함정

- **시각 정확도가 최우선 KPI.** title/timezone 퍼지는 허용.
- 폰 빌드는 사용자가 Android Studio에서. **CLI gradle 빌드 금지**(빌드 디렉토리 잠금 사고 전례).
- 합성 데이터는 에이전트가 직접 생성 + 로컬 무료 검증 우선(유료 Haiku 파이프라인은 보조).
- 유료 API 큰 작업 전 잔액 대비 예상비용 보고.
- `prompts/*.md` 수정 시 정규식 파싱(헤더/펜스) 깨지 않기. 모델 출력은 `_common.safe_json_loads`로 파싱.
- `build_user_block` 입력 포맷을 바꾸면 train·eval·앱(`ScheduleExtractor`/`DateResolver`) 세 곳을 함께 맞춰야 분포 불일치가 안 난다.
- PAT/OAuth/API 키를 채팅에 붙여넣지 말 것 — Kaggle/Colab의 getpass에 사용자가 직접 입력.

---

## 6. 트러블슈팅 메모

| 증상 | 원인 / 해결 |
|------|------------|
| 폰이 6/1 등 엉뚱한 날짜 추출 | (구) 0.5B 주말 횡단 산술 실패 → extract-resolve로 해결. 신모델+신앱 한 쌍인지 확인. |
| 모델 계보 헷갈림 | 폴더 mtime 말고 **내부 파일 mtime + adapter sha256**으로 판단. |
| Kaggle 학습물 증발 | 세션 정리. 끝나면 즉시 zip 다운로드. |
| `bf16` T4에서 느림(~28s/step) | T4는 bf16 에뮬레이션. 품질 위해 감수하거나 **T4x2 DDP**로 절반(~14s/step). |
| `torchao` ImportError | `pip uninstall torchao -y` (LoRA엔 불필요). 노트북 셀에 포함됨. |
| 한글 깨짐 (PowerShell) | `PYTHONUTF8=1` 또는 `chcp 65001`. merge/eval 콘솔 출력 cp1252 크래시 방지. |

---

## 7. 사용자 정보

- 이름: Soo (`soo@vibezent.com`). 한국어 대화 선호, 기술 용어 영어 OK.
- 머신: Windows 11, MX150 2GB VRAM (로컬은 데이터/merge/quantize/추론검증, 학습은 클라우드 GPU).
- 작업 폴더: `D:\calendar-agent`.
