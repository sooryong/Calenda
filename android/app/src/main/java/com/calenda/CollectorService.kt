package com.calenda

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/**
 * 상주 포그라운드 서비스. 자체로 메시지를 받지 않고(수신은 카톡 리스너/SMS 리시버가 담당),
 * '프로세스를 살려두는' 역할만 한다 → SMS 수신 후 LLM 추론(수 초)이 프로세스 종료로 끊기지 않게.
 * START_STICKY + BootReceiver로 재부팅/강제종료 후에도 복원. 상태 알림(낮은 우선순위)을 표시.
 */
class CollectorService : Service() {

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIF_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "수집 상태", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "백그라운드 자동 수집 상주 알림"
                },
            )
        }
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_my_calendar)
            .setContentTitle("일정 자동 수집 중")
            .setContentText("메시지에서 일정을 감지합니다")
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "collector"
        private const val NOTIF_ID = 42

        fun start(ctx: Context) {
            ContextCompat.startForegroundService(ctx, Intent(ctx, CollectorService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, CollectorService::class.java))
        }
    }
}
