package com.calenda

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast

/**
 * 일정 카드 탭 → 원본 메시지 앱 열기.
 * SMS는 발신자 대화방으로 딥링크(가능 시), 카톡·Gmail은 앱을 연다(특정 메시지 딥링크 미지원).
 * 앱이 설치되어 있지 않으면 토스트로 안내.
 */
object SourceNavigator {

    /** 채널에 맞는 앱을 연다. */
    fun openSource(ctx: Context, event: DetectedEvent) {
        when (event.channel) {
            "sms"   -> openSmsApp(ctx, event.sender)
            "kakao" -> openKakaoTalk(ctx)
            "gmail" -> openGmail(ctx)
            else    -> toast(ctx, ctx.getString(R.string.source_not_found))
        }
    }

    // ── 채널별 앱 열기 ──────────────────────────────────────────────────────

    /** SMS: 발신자 번호가 있으면 그 대화방으로, 없으면 메시지 앱 메인으로. */
    private fun openSmsApp(ctx: Context, sender: String) {
        val number = sender.filter { it.isDigit() || it == '+' }
        if (number.isNotEmpty()) {
            val thread = Intent(Intent.ACTION_VIEW, Uri.parse("smsto:$number"))
            if (startSafe(ctx, thread)) return
        }
        val main = Intent(Intent.ACTION_MAIN).apply { type = "vnd.android-dir/mms-sms" }
        if (!startSafe(ctx, main)) {
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
            false
        }
    }

    private fun toast(ctx: Context, msg: String) =
        Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show()
}
