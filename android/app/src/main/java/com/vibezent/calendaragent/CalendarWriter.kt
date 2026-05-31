package com.vibezent.calendaragent

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CalendarContract
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * CalendarProvider에 직접 insert/delete (사용자 상호작용 없이 = 고신뢰도 자동 등록 및 되돌리기용).
 * WRITE_CALENDAR/READ_CALENDAR 권한 필요. 사용자가 시스템 UI로 확인하는 경로는 CalendarInserter(ACTION_INSERT).
 */
object CalendarWriter {

    fun hasPermission(ctx: Context): Boolean =
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.WRITE_CALENDAR) == PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED

    /** 등록 성공 시 event _id, 실패/권한없음/캘린더없음 시 null. */
    fun insert(ctx: Context, event: CalendarEvent): Long? {
        if (!hasPermission(ctx)) return null
        val startMs = parseIso(event.start) ?: return null
        val calId = primaryCalendarId(ctx) ?: return null
        val tz = TimeZone.getDefault().id

        val values = ContentValues().apply {
            put(CalendarContract.Events.CALENDAR_ID, calId)
            put(CalendarContract.Events.TITLE, event.title)
            event.location?.let { put(CalendarContract.Events.EVENT_LOCATION, it) }
            buildDescription(event)?.let { put(CalendarContract.Events.DESCRIPTION, it) }
            put(CalendarContract.Events.DTSTART, startMs)
            put(CalendarContract.Events.EVENT_TIMEZONE, tz)
            val rrule = event.recurrence
            if (rrule != null) {
                // 반복 일정은 DTEND 대신 DURATION 필요 (CalendarProvider 규약).
                put(CalendarContract.Events.RRULE, rrule)
                put(CalendarContract.Events.DURATION, "PT1H")
            } else if (event.allDay) {
                put(CalendarContract.Events.ALL_DAY, 1)
                put(CalendarContract.Events.DTEND, startMs + 24 * 60 * 60 * 1000L)
            } else {
                put(CalendarContract.Events.DTEND, parseIso(event.end) ?: (startMs + 60 * 60 * 1000L))
            }
        }
        return try {
            ctx.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)
                ?.let { ContentUris.parseId(it) }
        } catch (e: Exception) {
            null
        }
    }

    /** 자동 등록 되돌리기: calendar event 삭제. */
    fun delete(ctx: Context, calendarEventId: Long): Boolean {
        if (!hasPermission(ctx)) return false
        return try {
            val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, calendarEventId)
            ctx.contentResolver.delete(uri, null, null) > 0
        } catch (e: Exception) {
            false
        }
    }

    /** 쓰기 가능한 기본(또는 첫) 캘린더 id. */
    private fun primaryCalendarId(ctx: Context): Long? {
        val proj = arrayOf(CalendarContract.Calendars._ID)
        val sel = "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ${CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR} " +
            "AND ${CalendarContract.Calendars.VISIBLE} = 1"
        ctx.contentResolver.query(
            CalendarContract.Calendars.CONTENT_URI, proj, sel, null,
            "${CalendarContract.Calendars.IS_PRIMARY} DESC",
        )?.use { c -> if (c.moveToFirst()) return c.getLong(0) }
        return null
    }

    private fun buildDescription(event: CalendarEvent): String? {
        val parts = mutableListOf<String>()
        event.description?.let { parts.add(it) }
        if (event.attendees.isNotEmpty()) parts.add("참석자: " + event.attendees.joinToString(", "))
        return if (parts.isEmpty()) null else parts.joinToString("\n")
    }

    /** ISO 8601 → epoch millis. tz 없으면 기기 로컬. (CalendarInserter와 동일 규약) */
    private fun parseIso(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        val hasTz = Regex("([+-]\\d{2}:?\\d{2}|Z)$").containsMatchIn(iso)
        val patterns = if (hasTz) listOf("yyyy-MM-dd'T'HH:mm:ssXXX", "yyyy-MM-dd'T'HH:mmXXX")
        else listOf("yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd")
        for (p in patterns) {
            try {
                val fmt = SimpleDateFormat(p, Locale.US)
                if (!hasTz) fmt.timeZone = TimeZone.getDefault()
                return (fmt.parse(iso) ?: continue).time
            } catch (_: Exception) { /* try next */ }
        }
        return null
    }
}
