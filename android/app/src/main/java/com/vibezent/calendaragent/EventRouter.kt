package com.vibezent.calendaragent

import android.content.Context
import android.util.Log

/**
 * 저장된 감지 일정을 등록 정책에 따라 라우팅한다.
 *   - 자동등록 ON & confidence ≥ 임계값 & 캘린더 권한 있음 → 바로 등록(AUTO_ADDED) + '되돌리기' 알림
 *   - 그 외 → 확인 알림(추가/무시 액션)으로 사용자에게 위임 (상태 PENDING 유지)
 */
object EventRouter {
    private const val TAG = "EventRouter"

    suspend fun route(
        appCtx: Context, repo: EventRepository, id: Long, event: CalendarEvent, msg: IncomingMessage,
    ) {
        val settings = SettingsStore.from(appCtx)
        val autoEligible = settings.autoAddEnabled &&
            event.confidence >= settings.confidenceThreshold &&
            CalendarWriter.hasPermission(appCtx)

        if (autoEligible) {
            val calId = CalendarWriter.insert(appCtx, event)
            if (calId != null) {
                repo.setStatus(id, EventStatus.AUTO_ADDED, calId)
                ScheduleNotifier.notifyAutoAdded(appCtx, event, msg, id)
                Log.d(TAG, "auto-added event $id (conf=${event.confidence})")
                return
            }
            Log.w(TAG, "auto-add insert failed → fall back to confirm")
        }
        // 확인 경로
        ScheduleNotifier.notifyConfirm(appCtx, event, msg, id)
    }
}
