package com.vibezent.calendaragent

import android.content.Context
import java.io.File

/**
 * GGUF 모델 파일 위치 + 로드 상태를 한 곳에서 관리.
 * MainActivity(수동)와 백그라운드 수집(리시버/리스너)이 같은 경로·인스턴스를 쓰도록 중앙화.
 */
object ModelStore {
    /**
     * 임포트된 모델이 저장되는 고정 슬롯 파일명 (실제 내용은 사용자가 임포트한 gguf).
     * 라운드 무관 고정 — 새 라운드(r3, r4...) gguf를 임포트해도 이 슬롯에 덮어쓴다.
     */
    const val FILE_NAME = "calendar.Q4_K_M.gguf"

    fun modelFile(ctx: Context): File = File(ctx.getExternalFilesDir(null), FILE_NAME)

    fun exists(ctx: Context): Boolean = modelFile(ctx).exists()

    /**
     * 모델이 로드돼 있지 않으면 디스크에서 로드 시도. 백그라운드 추론 진입점에서 호출.
     * 모델 파일이 없으면 false (수집은 조용히 스킵).
     */
    @Synchronized
    fun ensureLoaded(ctx: Context): Boolean {
        if (LlamaBridge.loaded) return true
        val f = modelFile(ctx)
        return if (f.exists()) LlamaBridge.loadModel(f.absolutePath) else false
    }
}
