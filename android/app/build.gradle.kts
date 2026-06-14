plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

android {
    namespace = "com.calenda"
    compileSdk = 36

    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "com.calenda"   // 설치 식별자 = 코드 패키지(통일). OAuth 클라이언트도 이 패키지.
        minSdk = 33
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        ndk {
            // 실기기(arm64) + 에뮬레이터(x86_64) 둘 다 빌드
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                arguments += "-DCMAKE_BUILD_TYPE=Release"
                arguments += "-DBUILD_SHARED_LIBS=ON"
                arguments += "-DLLAMA_BUILD_COMMON=OFF"
                arguments += "-DLLAMA_BUILD_TESTS=OFF"
                arguments += "-DLLAMA_BUILD_EXAMPLES=OFF"
                arguments += "-DLLAMA_BUILD_TOOLS=OFF"
                arguments += "-DLLAMA_BUILD_SERVER=OFF"
                arguments += "-DLLAMA_CURL=OFF"
                arguments += "-DGGML_NATIVE=OFF"
                arguments += "-DGGML_OPENMP=OFF"
            }
        }
    }

    externalNativeBuild {
        cmake {
            path("src/main/cpp/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // 이벤트함 영속화 (Room). KSP 사용 — kapt는 Kotlin 2.2 메타데이터를 못 읽어 실패(2.0까지만).
    implementation("androidx.room:room-runtime:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    ksp("androidx.room:room-compiler:2.8.4")

    // UI(이벤트함 목록·화면) + 생명주기 (Phase 3에서 사용)
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")

    // Gmail 풀바디 연동(opt-in): OAuth gmail.readonly 인가 → REST로 본문 전체 수집.
    //   알림 캡처(미리보기 잘림)로 못 보던 묻힌 일정을 잡기 위함. 폴링은 WorkManager.
    //   ※ google-api-services-gmail(무거운 구버전 http클라)는 안 씀 — AuthorizationClient(토큰) + OkHttp(REST) + org.json만.
    implementation("com.google.android.gms:play-services-auth:21.3.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
}
