package com.calenda

import android.content.Context
import android.util.Log
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * 저장된 감지 일정을 schedule_status(2-way)에 따라 라우팅한다.
 *   - status="yes"(확정) & 캘린더 권한 & 제목+일시 충족 → 바로 등록(AUTO_ADDED) + '되돌리기' 알림
 *   - status="yes"지만 이벤트 일시가 과거이면 → 확인 알림(오탐 방지)
 *   - status="yes"지만 권한/조건 미충족 → 확인 알림. 놓침 없음, 한 번 탭하면 등록.
 *   - status="no" → 아무것도 안 함.
 *
 * 안전 게이트: 제목(What)과 일시(When)가 모두 명확할 때만 자동 등록.
 */
object EventRouter {
    private const val TAG = "EventRouter"

    private val ISO_DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd")

    /** 등록 기준 충족? What=제목, When=일시(start). 장소는 요구하지 않음(없어도 등록). */
    private fun meetsStrictCriteria(e: CalendarEvent): Boolean =
        e.title.isNotBlank() &&
            !e.start.isNullOrBlank()

    suspend fun route(
        appCtx: Context, repo: EventRepository, id: Long, event: CalendarEvent, msg: IncomingMessage,
        status: String,
    ) {
        // 과거 일정은 yes여도 자동등록하지 않고 확인 알림으로 위임(오탐 방지).
        // 2-way 스키마: 오늘 확정 일정도 yes이므로 오늘은 자동등록 허용.
        val isPast = status == "yes" && run {
            val start = event.start ?: return@run false
            try {
                val eventDate = LocalDate.parse(start.take(10), ISO_DATE)
                eventDate.isBefore(LocalDate.now())
            } catch (_: Exception) { false }
        }
        if (isPast) {
            Log.d(TAG, "event $id start=${event.start} is past → skip auto-add")
        }

        val autoEligible = status == "yes" && !isPast &&
            CalendarWriter.hasPermission(appCtx) &&
            meetsStrictCriteria(event)

        if (autoEligible) {
            val calId = CalendarWriter.insert(appCtx, event)
            if (calId != null) {
                repo.setStatus(id, EventStatus.AUTO_ADDED, calId)
                ScheduleNotifier.notifyAutoAdded(appCtx, event, msg, id)
                Log.d(TAG, "auto-added event $id (status=$effectiveStatus)")
                return
            }
            Log.w(TAG, "auto-add insert failed → fall back to confirm")
        }
        // 확인 경로 (yes지만 자동등록 조건 미충족)
        ScheduleNotifier.notifyConfirm(appCtx, event, msg, id)
    }
}
