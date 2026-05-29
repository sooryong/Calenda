# Calendar Agent — Android MVP

온디바이스 GGUF(Qwen2.5-0.5B 파인튜닝) 추론으로 메시지에서 일정을 추출하고,
사용자 확인을 거쳐 캘린더에 등록하는 안드로이드 앱.

이 버전은 **MVP**: 메시지를 직접 붙여넣어 추출을 테스트하고, 결과를 캘린더에 등록한다.
SMS/카카오톡/Gmail 자동 수집은 Phase 2 (NotificationListenerService).

---

## 아키텍처

```
[메시지 입력 UI]
   → ScheduleExtractor (Qwen ChatML 프롬프트 빌드)
   → LlamaBridge (JNI) → libcalendaragent.so → llama.cpp (CPU 추론)
   → JSON 파싱 (has_schedule / events)
   → 미리보기 → CalendarInserter (Intent.ACTION_INSERT, 사용자 확인 저장)
```

- `LlamaBridge.kt` / `cpp/llama_jni.cpp` — 모델 로드 + 그리디 완성
- `ScheduleExtractor.kt` — 프롬프트 포맷(학습과 동일) + 출력 JSON 파싱
- `CalendarInserter.kt` — tz 없는 시각은 **기기 로컬 타임존**으로 해석 후 캘린더 Intent
- `MainActivity.kt` — UI, 코루틴으로 추론을 백그라운드 실행

---

## 빌드 전제

- Android Studio (Koala 이상 권장)
- NDK 28.2.13676358 (SDK Manager에서 설치)
- CMake 3.31.6 (SDK Manager에서 설치)
- minSdk 33, compileSdk 36

native 빌드 시 `CMakeLists.txt`가 **llama.cpp b9371을 FetchContent로 자동 다운로드**한다
(첫 빌드에 인터넷 + 수 분 소요). 오프라인이거나 로컬 클론을 쓰려면:

`android/local.properties`에:
```
# 선택: 로컬 llama.cpp 사용 (기본은 자동 다운로드)
```
또는 `app/build.gradle.kts`의 cmake arguments에
`-DLLAMA_CPP_DIR=D:/llama.cpp` 추가.

---

## 빌드 & 실행

1. Android Studio에서 `android/` 폴더 열기
2. Gradle sync (의존성 다운로드)
3. 기기 연결 또는 에뮬레이터 (arm64-v8a 권장; x86_64 에뮬레이터도 지원)
4. Run ▶

> 첫 빌드는 llama.cpp 컴파일 때문에 수 분 걸린다. 이후는 캐시됨.

---

## 모델 파일 올리기

GGUF(~374MB)는 APK에 포함하지 않는다(앱 비대). 앱은 라운드 무관 고정 슬롯
`calendar.Q4_K_M.gguf`로 저장하므로, 새 라운드 gguf를 임포트하면 같은 슬롯에 덮어쓴다. 두 방법:

### 방법 A — 앱에서 임포트 (권장)
1. 모델 파일을 기기로 복사 (USB, 클라우드, Downloads 등)
2. 앱 실행 → **"모델 파일 임포트 (.gguf)"** → 파일 선택
3. 앱이 내부 저장소로 복사 후 자동 로드

### 방법 B — adb push
```
adb push models/gguf/r3-qwen/*.Q4_K_M.gguf \
  /sdcard/Android/data/com.vibezent.calendaragent/files/calendar.Q4_K_M.gguf
```
→ 앱에서 **"모델 로드"** 클릭

---

## 사용

1. 채널/발신자/수신시각/메시지 입력 (수신시각은 기본 현재시각)
2. **일정 추출** → CPU 추론 (수 초)
3. 결과(has_schedule, 이벤트 필드) 확인
4. **캘린더에 추가** → 시스템 캘린더 앱이 열리고 미리 채워진 상태로 표시 → 저장

---

## 알려진 한계 / Phase 2

- 현재 멀티이벤트는 첫 번째만 캘린더 버튼으로 등록 (리스트 UI 추후)
- 자동 메시지 수집 미구현 — NotificationListenerService로 SMS/카톡/Gmail 알림 캡처 예정
  (카카오톡은 공식 API 없음 — 알림 가로채기 방식, ToS 유의)
- on-device 추론 속도는 기기 CPU에 따라 다름 (노트북 CPU 기준 ~26 tok/s, 폰은 기기별)
