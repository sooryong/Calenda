package com.calenda

import android.content.Context
import android.util.Log
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * 저장된 감지 일정을 schedule_status(3-way)에 따라 라우팅한다. (c2: confidence 폐지)
 *   - status="yes"(확정) & 자동등록 ON & 캘린더 권한 & 제목+일시 충족 & 내일 이후 → 바로 등록(AUTO_ADDED) + '되돌리기' 알림
 *   - status="pending"(공고·안내·초대·미확정 제안) → 항상 확인 알림(예비). 자동등록하지 않음.
 *   - status="yes"지만 이벤트 일시가 오늘이면 → pending 취급(사용자 확인). 당일 완료·결제 알림 오탐 방지.
 *   - 그 외(yes지만 권한/조건 미충족) → 확인 알림. 놓침 없음, 한 번 탭하면 등록.
 *
 * 안전 게이트(항상 적용, 토글 폐지): 제목(What)과 일시(When)가 모두 명확할 때만 자동 등록하고,
 * 하나라도 없으면(시각 미상 등) 예비로 보류해 오탐을 줄인다. 장소(Where)는 개인 일정엔 없는 경우가
 * 많아 자동 등록을 막지 않는다(없어도 등록). Who(누가)는 발신자가 항상 있으므로 검사하지 않는다.
 */
object EventRouter {
    private const val TAG = "EventRouter"

    private val ISO_DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd")

    /** 등록 기준 충족? What=제목, When=일시(start). 장소는 요구하지 않음(없어도 등록). */
    private fun meetsStrictCriteria(e: CalendarEvent): Boolean =
        e.title.isNotBlank() &&
            !e.start.isNullOrBlank()

    /**
     * 이벤트 시작 일시가 오늘이거나 과거이면 true.
     * 결제 완료 알림 등이 당일 시각을 이벤트 시각으로 오인하는 경우를 자동등록에서 제외한다.
     * start가 없거나 파싱 실패하면 false(안전 방향 — 자동등록 경로 유지).
     */
    private fun isTodayOrPast(event: CalendarEvent): Boolean {
        val start = event.start ?: return false
        return try {
            val eventDate = LocalDate.parse(start.take(10), ISO_DATE)
            !eventDate.isAfter(LocalDate.now())
        } catch (_: Exception) {
            false
        }
    }

    suspend fun route(
        appCtx: Context, repo: EventRepository, id: Long, event: CalendarEvent, msg: IncomingMessage,
        status: String,
    ) {
        // 오늘·과거 일정은 yes여도 자동등록하지 않고 사용자 확인으로 위임.
        // 결제일시(오늘)를 이벤트 시각으로 오인한 오탐을 막는 2차 게이트.
        val effectiveStatus = if (status == "yes" && isTodayOrPast(event)) {
            Log.d(TAG, "event $id start=${event.start} is today/past → demote yes→pending")
            "pending"
        } else {
            status
        }

        // 자동등록은 확정("yes")만. pending은 항상 사용자 확인(예비)으로 위임.
        // 제목·일시 없는 yes는 자동등록 대신 예비(안전 게이트). (자동등록 토글 폐지 — yes는 항상 자동.)
        val autoEligible = effectiveStatus == "yes" &&
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
        // 확인 경로 (pending, 또는 yes지만 자동등록 조건 미충족)
        ScheduleNotifier.notifyConfirm(appCtx, event, msg, id)
    }
}
