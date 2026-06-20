package com.calenda

import android.content.Context

/**
 * 사용자 설정 (SharedPreferences). 등록 정책·채널 토글의 단일 출처.
 * 파이프라인/라우터/UI가 공유한다.
 */
class SettingsStore(ctx: Context) {
    private val prefs = ctx.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

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

    /** Gmail 풀바디 연동(opt-in). 사용자가 OAuth 인가를 마치면 true → WorkManager 폴링 시작.
     *  채널 토글(channelEnabled("gmail"))과 별개: 채널=알림 캡처 on/off, 이 값=풀바디 API on/off.
     *  풀바디가 켜지면 같은 메일을 알림에서도 보므로 dedupeKey가 중복을 막는다(둘 켜도 안전). */
    var gmailApiEnabled: Boolean
        get() = prefs.getBoolean(K_GMAIL_API, false)
        set(v) = prefs.edit().putBoolean(K_GMAIL_API, v).apply()

    /** 마지막으로 Gmail API에서 가져온 메일의 internalDate(ms). 이후 메일만 신규 처리(증분). 0=처음. */
    var gmailLastSyncMillis: Long
        get() = prefs.getLong(K_GMAIL_SYNC, 0L)
        set(v) = prefs.edit().putLong(K_GMAIL_SYNC, v).apply()

    /** Gmail 본문 읽기에 쓸 Google 계정명(= 선택한 캘린더 계정). 캘린더·Gmail을 한 ID로 통합. null=미설정. */
    var gmailAccount: String?
        get() = prefs.getString(K_GMAIL_ACCOUNT, null)
        set(v) = prefs.edit().putString(K_GMAIL_ACCOUNT, v).apply()

    private fun keyChannel(channel: String) = "channel_$channel"

    companion object {
        private const val K_COLLECTOR = "collector_enabled"
        private const val K_ONBOARDING = "onboarding_done"
        private const val K_CALENDAR = "target_calendar_id"
        private const val K_GMAIL_API = "gmail_api_enabled"
        private const val K_GMAIL_SYNC = "gmail_last_sync_millis"
        private const val K_GMAIL_ACCOUNT = "gmail_account"
        fun from(ctx: Context) = SettingsStore(ctx)
    }
}
