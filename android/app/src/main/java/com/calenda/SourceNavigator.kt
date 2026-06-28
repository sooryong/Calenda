package com.calenda

import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.CalendarContract
import android.widget.Toast

/**
 * 일정 카드 [소스] 탭 → 원본 앱 열기, [캘린더] 탭 → Google Calendar 이벤트 열기.
 * 앱이 설치되어 있지 않으면 토스트로 안내.
 */
object SourceNavigator {

    /** 채널에 맞는 앱을 연다. */
    fun openSource(ctx: Context, event: DetectedEvent) {
        when (event.channel) {
            "sms"   -> openSmsApp(ctx)
            "kakao" -> openKakaoTalk(ctx)
            "gmail" -> openGmail(ctx)
            else    -> toast(ctx, ctx.getString(R.string.source_not_found))
        }
    }

    /** 등록된 일정을 Google Calendar 앱에서 연다. */
    fun openCalendarEvent(ctx: Context, calendarEventId: Long) {
        val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, calendarEventId)
        val intent = Intent(Intent.ACTION_VIEW, uri)
        startSafe(ctx, intent)
    }

    // ── 채널별 앱 열기 ──────────────────────────────────────────────────────

    private fun openSmsApp(ctx: Context) {
        val intent = Intent(Intent.ACTION_MAIN).apply {
            type = "vnd.android-dir/mms-sms"
        }
        if (!startSafe(ctx, intent)) {
            // 폴백: 기본 다이얼러 없는 환경 — URI scheme
            startSafe(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("sms:")))
        }
    }

    private fun openKakaoTalk(ctx: Context) {
        val pm = ctx.packageManager
        val pkg = "com.kakao.talk"
        val launch = pm.getLaunchIntentForPackage(pkg)
        if (launch != null) {
            ctx.startActivity(launch)
        } else {
            // 미설치면 Play 스토어
            startSafe(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$pkg")))
        }
    }

    private fun openGmail(ctx: Context) {
        val pm = ctx.packageManager
        val pkg = "com.google.android.gm"
        val launch = pm.getLaunchIntentForPackage(pkg)
        if (launch != null) {
            ctx.startActivity(launch)
        } else {
            startSafe(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$pkg")))
        }
    }

    // ── 유틸 ────────────────────────────────────────────────────────────────

    /** startActivity를 시도하고, 앱 없으면 토스트 후 false 반환. */
    private fun startSafe(ctx: Context, intent: Intent): Boolean {
        return try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            true
        } catch (_: Exception) {
            toast(ctx, ctx.getString(R.string.source_not_found))
            false
        }
    }

    private fun toast(ctx: Context, msg: String) =
        Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show()
}
