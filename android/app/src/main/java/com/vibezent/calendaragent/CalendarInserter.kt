package com.vibezent.calendaragent

import android.content.Context
import android.content.Intent
import android.provider.CalendarContract
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Intent.ACTION_INSERT로 캘린더 앱을 띄워 사용자가 확인 후 저장하게 함.
 * 권한 불필요(시스템 캘린더 앱이 처리). 잘못 추출돼도 사용자가 거를 수 있어 안전.
 */
object CalendarInserter {

    /** 이벤트 1건 → 캘린더 등록 Intent 생성. start 파싱 실패 시 시간 미지정으로 띄움. */
    fun buildInsertIntent(event: CalendarEvent): Intent {
        val intent = Intent(Intent.ACTION_INSERT).apply {
            data = CalendarContract.Events.CONTENT_URI
            putExtra(CalendarContract.Events.TITLE, event.title)
            event.location?.let { putExtra(CalendarContract.Events.EVENT_LOCATION, it) }
            buildDescription(event)?.let { putExtra(CalendarContract.Events.DESCRIPTION, it) }

            val startMs = parseIsoToMillis(event.start)
            if (startMs != null) {
                putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, startMs)
                val endMs = parseIsoToMillis(event.end) ?: (startMs + 60 * 60 * 1000L) // 기본 1시간
                putExtra(CalendarContract.EXTRA_EVENT_END_TIME, endMs)
            }
            if (event.allDay) {
                putExtra(CalendarContract.EXTRA_EVENT_ALL_DAY, true)
            }
            event.recurrence?.let { putExtra(CalendarContract.Events.RRULE, it) }
        }
        return intent
    }

    fun launch(context: Context, event: CalendarEvent) {
        val intent = buildInsertIntent(event).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun buildDescription(event: CalendarEvent): String? {
        val parts = mutableListOf<String>()
        event.description?.let { parts.add(it) }
        if (event.attendees.isNotEmpty()) parts.add("참석자: " + event.attendees.joinToString(", "))
        return if (parts.isEmpty()) null else parts.joinToString("\n")
    }

    /**
     * ISO 8601 → epoch millis.
     * - tz 포함(+09:00, Z 등): 그대로 해석
     * - tz 미포함: 기기 로컬 타임존으로 해석 (사용자 정책: "스마트폰 시간대 기준")
     */
    private fun parseIsoToMillis(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        val hasTz = Regex("([+-]\\d{2}:?\\d{2}|Z)$").containsMatchIn(iso)
        val patterns = if (hasTz) {
            listOf("yyyy-MM-dd'T'HH:mm:ssXXX", "yyyy-MM-dd'T'HH:mmXXX")
        } else {
            listOf("yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd")
        }
        for (p in patterns) {
            try {
                val fmt = SimpleDateFormat(p, Locale.US)
                if (!hasTz) fmt.timeZone = TimeZone.getDefault()
                val d: Date = fmt.parse(iso) ?: continue
                return d.time
            } catch (_: Exception) { /* try next */ }
        }
        return null
    }
}
