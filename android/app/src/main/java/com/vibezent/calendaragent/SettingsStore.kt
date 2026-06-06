package com.vibezent.calendaragent

import android.content.Context

/**
 * 사용자 설정 (SharedPreferences). 등록 정책·채널 토글의 단일 출처.
 * 파이프라인/라우터/UI가 공유한다.
 */
class SettingsStore(ctx: Context) {
    private val prefs = ctx.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    /** 고신뢰도 자동 등록 on/off. */
    var autoAddEnabled: Boolean
        get() = prefs.getBoolean(K_AUTO_ADD, true)
        set(v) = prefs.edit().putBoolean(K_AUTO_ADD, v).apply()

    /** 이 값 이상이면 자동 등록, 미만이면 확인 알림. */
    var confidenceThreshold: Float
        get() = prefs.getFloat(K_THRESHOLD, 0.85f)
        set(v) = prefs.edit().putFloat(K_THRESHOLD, v).apply()

    /** 엄격 등록: 제목·일시·장소(What·When·Where)가 모두 있어야 자동 등록. Who는 발신자로 충족. 하나라도 없으면 예비. */
    var strictRegister: Boolean
        get() = prefs.getBoolean(K_STRICT, true)
        set(v) = prefs.edit().putBoolean(K_STRICT, v).apply()

    fun channelEnabled(channel: String): Boolean =
        prefs.getBoolean(keyChannel(channel), true)

    fun setChannelEnabled(channel: String, enabled: Boolean) =
        prefs.edit().putBoolean(keyChannel(channel), enabled).apply()

    /** 자동 수집(포그라운드 서비스) 사용 여부 — 사용자가 토글. */
    var collectorEnabled: Boolean
        get() = prefs.getBoolean(K_COLLECTOR, false)
        set(v) = prefs.edit().putBoolean(K_COLLECTOR, v).apply()

    /** 첫 실행 온보딩 완료 여부. */
    var onboardingDone: Boolean
        get() = prefs.getBoolean(K_ONBOARDING, false)
        set(v) = prefs.edit().putBoolean(K_ONBOARDING, v).apply()

    /** 자동등록 저장 대상 캘린더 id. -1 = 미설정(CalendarWriter가 자동 선택). */
    var targetCalendarId: Long
        get() = prefs.getLong(K_CALENDAR, -1L)
        set(v) = prefs.edit().putLong(K_CALENDAR, v).apply()

    private fun keyChannel(channel: String) = "channel_$channel"

    companion object {
        private const val K_AUTO_ADD = "auto_add"
        private const val K_THRESHOLD = "confidence_threshold"
        private const val K_STRICT = "strict_register"
        private const val K_COLLECTOR = "collector_enabled"
        private const val K_ONBOARDING = "onboarding_done"
        private const val K_CALENDAR = "target_calendar_id"
        fun from(ctx: Context) = SettingsStore(ctx)
    }
}
