package com.vibezent.calendaragent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 알림 액션 처리: 추가 / 무시 / 되돌리기. Room 상태를 갱신하고 캘린더에 반영한다.
 * goAsync로 짧은 백그라운드 작업(DB/Provider)을 안전하게 수행.
 */
class EventActionReceiver : BroadcastReceiver() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getLongExtra(EXTRA_ID, -1L)
        val notifId = intent.getIntExtra(EXTRA_NOTIF_ID, -1)
        val action = intent.action ?: return
        if (id < 0) return
        val appCtx = context.applicationContext
        val pending = goAsync()
        scope.launch {
            try {
                val repo = EventRepository.from(appCtx)
                val ev = repo.get(id)
                when (action) {
                    ACTION_ADD -> if (ev != null) {
                        val calId = CalendarWriter.insert(appCtx, ev.toCalendarEvent())
                        repo.setStatus(id, EventStatus.ADDED, calId)
                    }
                    ACTION_DISMISS -> repo.setStatus(id, EventStatus.DISMISSED, null)
                    ACTION_UNDO -> {
                        ev?.calendarEventId?.let { CalendarWriter.delete(appCtx, it) }
                        repo.setStatus(id, EventStatus.DISMISSED, null)
                    }
                }
                if (notifId >= 0) NotificationManagerCompat.from(appCtx).cancel(notifId)
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_ADD = "com.vibezent.calendaragent.action.ADD"
        const val ACTION_DISMISS = "com.vibezent.calendaragent.action.DISMISS"
        const val ACTION_UNDO = "com.vibezent.calendaragent.action.UNDO"
        const val EXTRA_ID = "event_id"
        const val EXTRA_NOTIF_ID = "notif_id"
    }
}
