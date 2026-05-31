package com.vibezent.calendaragent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * 백그라운드 감지 결과 알림. 두 종류:
 *   - notifyConfirm   : 확인 필요(추가/무시 액션) — 저신뢰도 또는 자동등록 OFF
 *   - notifyAutoAdded : 자동 등록 완료(되돌리기 액션) — 고신뢰도
 * 알림 id = event id(.toInt) 로 고정 → 액션이 같은 알림을 취소할 수 있다.
 */
object ScheduleNotifier {
    private const val CHANNEL_ID = "schedule_detected"

    private fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "일정 감지", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "메시지에서 일정이 감지되면 알림"
                },
            )
        }
    }

    private fun actionIntent(ctx: Context, action: String, id: Long, notifId: Int): PendingIntent {
        val i = Intent(ctx, EventActionReceiver::class.java).apply {
            this.action = action
            putExtra(EventActionReceiver.EXTRA_ID, id)
            putExtra(EventActionReceiver.EXTRA_NOTIF_ID, notifId)
        }
        return PendingIntent.getBroadcast(
            ctx, action.hashCode() * 31 + id.toInt(), i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun openAppIntent(ctx: Context, notifId: Int): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        return PendingIntent.getActivity(
            ctx, notifId, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun summary(event: CalendarEvent): String {
        val whenStr = event.start ?: "(시간 미정)"
        val where = event.location?.let { " · $it" } ?: ""
        return "$whenStr$where"
    }

    /** 확인 필요: 추가/무시 액션. */
    fun notifyConfirm(ctx: Context, event: CalendarEvent, source: IncomingMessage, id: Long) {
        ensureChannel(ctx)
        val notifId = id.toInt()
        val n = NotificationCompat.Builder(ctx, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_my_calendar)
            .setContentTitle("일정 발견: ${event.title}")
            .setContentText("${summary(event)}  (${source.channel})")
            .setStyle(NotificationCompat.BigTextStyle().bigText("${summary(event)}\n\n원본: ${source.body}"))
            .setContentIntent(openAppIntent(ctx, notifId))
            .setAutoCancel(true)
            .addAction(android.R.drawable.ic_menu_add, "추가",
                actionIntent(ctx, EventActionReceiver.ACTION_ADD, id, notifId))
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "무시",
                actionIntent(ctx, EventActionReceiver.ACTION_DISMISS, id, notifId))
            .build()
        post(ctx, notifId, n)
    }

    /** 자동 등록 완료: 되돌리기 액션. */
    fun notifyAutoAdded(ctx: Context, event: CalendarEvent, source: IncomingMessage, id: Long) {
        ensureChannel(ctx)
        val notifId = id.toInt()
        val n = NotificationCompat.Builder(ctx, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_my_calendar)
            .setContentTitle("자동 등록됨: ${event.title}")
            .setContentText("${summary(event)}  (${source.channel})")
            .setStyle(NotificationCompat.BigTextStyle().bigText("캘린더에 추가했습니다.\n${summary(event)}\n\n원본: ${source.body}"))
            .setContentIntent(openAppIntent(ctx, notifId))
            .setAutoCancel(true)
            .addAction(android.R.drawable.ic_menu_revert, "되돌리기",
                actionIntent(ctx, EventActionReceiver.ACTION_UNDO, id, notifId))
            .build()
        post(ctx, notifId, n)
    }

    private fun post(ctx: Context, notifId: Int, n: Notification) {
        try {
            NotificationManagerCompat.from(ctx).notify(notifId, n)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS 미허용 — 조용히 무시
        }
    }
}
