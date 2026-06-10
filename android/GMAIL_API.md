# Gmail 풀바디 연동 (opt-in OAuth gmail.readonly)

> 왜: 앱은 Gmail을 **알림(NotificationListener)** 으로만 받는다. 알림 미리보기는 본문 앞 ~130자에서 끊겨,
> 일정 문장이 2~3문단째에 있으면(예: 대구창조경제혁신센터 "6월 16일(화) … 출범식") **모델에 도달조차 못 한다.**
> → opt-in으로 OAuth `gmail.readonly` 인가를 받아 **본문 전체**를 REST로 가져와 같은 파이프라인에 넣는다.

## 아키텍처 (구현됨 — 스캐폴딩)

```
SettingsActivity ──[Gmail 본문 전체 연동] 버튼──> Identity.AuthorizationClient.authorize(gmail.readonly)
        │                                              │ 최초/만료: PendingIntent 동의화면
        │ onGmailAuthorized(accessToken)               ▼
        ├─> SettingsStore.gmailApiEnabled = true     사용자 동의
        ├─> GmailSyncWorker.enable()  (30분 주기, 네트워크 연결 시)
        └─> GmailApiClient.sync(token) 즉시 1회

GmailSyncWorker(주기) ─> GmailApiClient.silentToken()  // 무-UI, 동의돼 있으면 토큰
        └─> GmailApiClient.sync(token):
              messages?q=in:inbox newer_than:3d        // 최근 메일 id
              messages/{id}?format=full                // 본문 전체(text/plain 우선, 없으면 html strip)
              internalDate > lastSync 인 것만 (증분)
              MessagePipeline.onMessage(channel="gmail", sender=From, body=제목+본문, ms=internalDate)
                  └─> 휴리스틱 → 모델 → DateResolver → EventRepository.save(dedupeKey)
```

핵심 파일:
- `GmailApiClient.kt` — 인가요청·무-UI토큰·REST fetch/파싱·파이프라인 주입.
- `GmailSyncWorker.kt` — WorkManager 주기 폴링(`enable`/`disable`).
- `SettingsActivity.kt` — opt-in 버튼(`toggleGmailApi`/`onGmailAuthorized`), `gmailAuthLauncher`.
- `SettingsStore.kt` — `gmailApiEnabled`, `gmailLastSyncMillis`(증분 기준).
- 의존성: `play-services-auth:21.3.0`(토큰) + `okhttp:4.12.0`(REST) + `work-runtime-ktx:2.9.1`(폴링). `INTERNET` 권한.

설계 의도:
- 무거운 `google-api-services-gmail`(구버전 http 클라 + desugaring) 안 씀 → 액세스 토큰 + OkHttp + `org.json`만.
- **알림 캡처와 풀바디를 둘 다 켜도 안전**: 같은 메일을 둘 다 봐도 `dedupeKey(channel|receivedAt|start|title)`가 중복 등록을 막는다.
- 읽기 전용(`gmail.readonly`). 본문만 읽고 어디에도 업로드하지 않음(온디바이스).

## ★ 사용자 1회 설정 — Google Cloud (이게 없으면 인가가 실패함)

`gmail.readonly`는 **restricted scope**다. 본인+지인 소수( ≤100 테스트 사용자 )면 **게시 상태 "테스트"** 로 두면
**CASA 보안평가·검증 없이** 동작한다(검증은 일반 공개/100명 초과 시에만 필요).

1. **Google Cloud Console** → 프로젝트 생성(또는 기존).
2. **API 및 서비스 → 라이브러리** → **Gmail API** 사용 설정.
3. **OAuth 동의 화면**:
   - User type: **외부**, 게시 상태: **테스트** 로 유지.
   - **범위 추가**: `https://www.googleapis.com/auth/gmail.readonly`.
   - **테스트 사용자**: 본인 Gmail(`sooryong.byun@gmail.com`)과 쓸 지인 계정 추가.
4. **사용자 인증 정보 → OAuth 클라이언트 ID 만들기**:
   - 애플리케이션 유형: **Android**.
   - 패키지 이름: **`com.calendaragent`** (= `applicationId`).
   - **SHA-1**: 디버그 키로
     `keytool -list -v -keystore %USERPROFILE%\.android\debug.keystore -alias androiddebugkey -storepass android -keypass android`
     의 SHA1 값 입력. (릴리스 서명으로 배포하면 릴리스 키 SHA-1도 추가.)
   > Android OAuth 클라이언트는 client-secret이 없고 (package + SHA-1)로 앱을 식별한다. 앱 코드에 ID를 박을 필요 없음 —
   > `AuthorizationClient`가 설치 서명으로 자동 매칭한다. 그래서 `GmailApiClient`에 클라이언트 ID 상수가 없다.

설정 후: 앱 **설정 → Gmail 본문 전체 연동** 버튼 → 계정 선택 + 동의 → 끝. 30분마다 새 메일 본문을 증분 수집.

## 빌드 / 검증

- Android Studio에서 **Gradle Sync**(새 의존성) 후 빌드. (CLI는 `gradlew :app:installDebug`, 단 Studio 닫고 — [[feedback_android_build_in_studio]].)
- 첫 검증: 본인에게 일정이 **본문 중간**에 묻힌 메일을 보내고(제목엔 일정 없음) 연동 켠 뒤 30분 내 또는 설정 재진입(즉시 1회 sync) → 이벤트함에 뜨는지.
- logcat: `GmailApiClient: sync: ingested=N`, `MessagePipeline: onMessage ch=gmail`.

## 모델 측 보강 (r20에 포함됨)

풀바디가 들어오면 **장문·격식·'참석 필수 아님' 헤지** 속 묻힌 일정을 양성으로 잡아야 한다.
r20 하드케이스(`build_r20_hardcases.py` G2)가 정확히 이 분포(격식 기관메일 선택적-참석 + 확정일자 행사)를 학습한다.
또 월-일 토큰(`6월16일`/`6/16`) resolver 지원(③)으로 "6월 16일(화)"이 연도 산술 없이 종일 일정으로 풀린다.

## 미구현/주의 (다음 단계)

- **토큰 만료/철회**: `silentToken`이 null이면 워커는 그 주기를 건너뛴다(retry 폭주 방지). 사용자가 설정에서 재인가하면 복구.
  더 매끈하게 하려면 연속 실패 시 알림으로 재인가 유도.
- **첫 동기화 범위**: 현재 `newer_than:3d` + `internalDate > lastSync`. 과거 메일 일괄 수집은 안 함(의도 — 노이즈/배터리).
- **history API 미사용**: 단순 폴링(증분=internalDate 비교). 트래픽 크면 `history.list`(historyId)로 최적화 여지.
- **컴파일 미검증**: 이 환경에서 Android 빌드를 못 돌렸다. Studio Gradle Sync로 의존성/시그니처 확인 필요.
