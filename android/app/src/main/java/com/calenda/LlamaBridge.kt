package com.calenda

/**
 * llama.cpp JNI 브리지. native 라이브러리(libcalendaragent.so) 로드 + 모델 추론.
 * 단일 모델 인스턴스 가정 (앱 전체에서 하나).
 */
object LlamaBridge {
    init {
        System.loadLibrary("calendaragent")
    }

    @Volatile
    var loaded: Boolean = false
        private set

    private external fun nativeLoadModel(modelPath: String): Boolean
    private external fun nativeComplete(prompt: String, nPredict: Int): String
    private external fun nativeFree()

    /** GGUF 모델 로드. 성공 시 true. */
    @Synchronized
    fun loadModel(modelPath: String): Boolean {
        loaded = nativeLoadModel(modelPath)
        return loaded
    }

    /** 프롬프트 → 생성 텍스트(그리디). 모델 미로드 시 에러 문자열 반환. */
    @Synchronized
    fun complete(prompt: String, nPredict: Int = 256): String {
        if (!loaded) return "[error] model not loaded"
        return nativeComplete(prompt, nPredict)
    }

    @Synchronized
    fun free() {
        nativeFree()
        loaded = false
    }
}
