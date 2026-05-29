package com.vibezent.calendaragent

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import java.util.concurrent.atomic.AtomicInteger

/**
 * 백그라운드 추출로 일정이 발견되면 알림을 띄운다.
 * 자동 등록하지 않고 사용자 확인을 거치도록, 탭 시 캘린더 추가 화면(CalendarInserter)을 연다.
 */
object ScheduleNotifier {
    private const val CHANNEL_ID = "schedule_detected"
    private val nextId = AtomicInteger(1000)

    private fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "일정 감지", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "메시지에서 일정이 감지되면 알림"
                }
            )
        }
    }

    /** 발견된 이벤트 1건을 알림으로. 탭하면 캘린더 추가 인텐트 실행. */
    fun notify(ctx: Context, event: CalendarEvent, source: IncomingMessage) {
        ensureChannel(ctx)

        val insert = CalendarInserter.buildInsertIntent(event).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val id = nextId.getAndIncrement()
        val pi = PendingIntent.getActivity(
            ctx, id, insert,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val when_ = event.start ?: "(시간 미정)"
        val where = event.location?.let { " · $it" } ?: ""
        val notif = NotificationCompat.Builder(ctx, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_my_calendar)
            .setContentTitle("일정 발견: ${event.title}")
            .setContentText("$when_$where  (${source.channel})")
            .setStyle(NotificationCompat.BigTextStyle().bigText("$when_$where\n\n원본: ${source.body}"))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .addAction(android.R.drawable.ic_menu_add, "캘린더에 추가", pi)
            .build()

        try {
            NotificationManagerCompat.from(ctx).notify(id, notif)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS 미허용 — 조용히 무시
        }
    }
}
