package com.calenda

import android.content.Context
import android.util.Log

/**
 * 저장된 감지 일정을 등록 정책에 따라 라우팅한다.
 *   - 자동등록 ON & confidence ≥ 임계값 & 캘린더 권한 있음 & (엄격모드면 What+When+Where 충족) → 바로 등록(AUTO_ADDED) + '되돌리기' 알림
 *   - 그 외 → 확인 알림(추가/무시 액션)으로 사용자에게 위임 (상태 PENDING 유지). 놓침 없음, 한 번 탭하면 등록.
 *
 * 엄격 등록(strictRegister): 제목(What)과 일시(When)가 모두 명확할 때만 자동 등록하고,
 * 하나라도 없으면 예비로 보류해 오탐을 줄인다. 장소(Where)는 개인 일정엔 없는 경우가 많아
 * 자동 등록을 막지 않는다(없어도 등록). Who(누가)는 발신자가 항상 있으므로 검사하지 않는다.
 */
object EventRouter {
    private const val TAG = "EventRouter"

    /** 등록 기준 충족? What=제목, When=일시(start). 장소는 요구하지 않음(없어도 등록). */
    private fun meetsStrictCriteria(e: CalendarEvent): Boolean =
        e.title.isNotBlank() &&
            !e.start.isNullOrBlank()

    suspend fun route(
        appCtx: Context, repo: EventRepository, id: Long, event: CalendarEvent, msg: IncomingMessage,
    ) {
        val settings = SettingsStore.from(appCtx)
        val autoEligible = settings.autoAddEnabled &&
            // 경계 오차 흡수: confidence는 Double, threshold는 Float(0.85f≈0.85000002)라
            // 모델이 정확히 0.85를 내면 0.85>=0.85f가 False가 돼 동률인데도 탈락하던 버그 방지.
            (event.confidence >= settings.confidenceThreshold - 1e-4) &&
            CalendarWriter.hasPermission(appCtx) &&
            (!settings.strictRegister || meetsStrictCriteria(event))

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
