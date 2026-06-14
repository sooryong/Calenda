package com.calenda

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
                // 종일: CalendarProvider 규약상 DTSTART/DTEND=UTC 자정, EVENT_TIMEZONE=UTC.
                // (로컬 자정으로 넣으면 Google Calendar가 날짜를 하루 당겨 표시/미표시함.)
                val dayUtc = parseDateUtc(event.start) ?: startMs
                put(CalendarContract.Events.ALL_DAY, 1)
                put(CalendarContract.Events.DTSTART, dayUtc)
                put(CalendarContract.Events.DTEND, dayUtc + 24 * 60 * 60 * 1000L)
                put(CalendarContract.Events.EVENT_TIMEZONE, "UTC")
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

    /** 기존 캘린더 일정 제자리 수정(편집 후 [업데이트]). 성공 시 true. */
    fun update(ctx: Context, calendarEventId: Long, event: CalendarEvent): Boolean {
        if (!hasPermission(ctx)) return false
        val startMs = parseIso(event.start) ?: return false
        val tz = TimeZone.getDefault().id

        val values = ContentValues().apply {
            put(CalendarContract.Events.TITLE, event.title)
            put(CalendarContract.Events.EVENT_LOCATION, event.location ?: "")      // 빈 문자열=장소 지움
            put(CalendarContract.Events.DESCRIPTION, buildDescription(event) ?: "")
            put(CalendarContract.Events.DTSTART, startMs)
            put(CalendarContract.Events.EVENT_TIMEZONE, tz)
            val rrule = event.recurrence
            if (rrule != null) {
                put(CalendarContract.Events.RRULE, rrule)
                put(CalendarContract.Events.DURATION, "PT1H")
                putNull(CalendarContract.Events.DTEND)
                put(CalendarContract.Events.ALL_DAY, 0)
            } else if (event.allDay) {
                val dayUtc = parseDateUtc(event.start) ?: startMs
                put(CalendarContract.Events.ALL_DAY, 1)
                put(CalendarContract.Events.DTSTART, dayUtc)
                put(CalendarContract.Events.DTEND, dayUtc + 24 * 60 * 60 * 1000L)
                put(CalendarContract.Events.EVENT_TIMEZONE, "UTC")
                putNull(CalendarContract.Events.RRULE)
                putNull(CalendarContract.Events.DURATION)
            } else {
                put(CalendarContract.Events.ALL_DAY, 0)
                put(CalendarContract.Events.DTEND, parseIso(event.end) ?: (startMs + 60 * 60 * 1000L))
                putNull(CalendarContract.Events.RRULE)
                putNull(CalendarContract.Events.DURATION)
            }
        }
        return try {
            val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, calendarEventId)
            ctx.contentResolver.update(uri, values, null, null) > 0
        } catch (e: Exception) {
            false
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

    // 미설정 시 폴백 선호 계정(설정에서 사용자가 고르면 그게 우선).
    private const val PREFERRED_ACCOUNT = "sooryong.byun@gmail.com"

    /** 캘린더 한 개의 표시 정보 (설정 피커·선택 로직 공용). */
    data class CalInfo(val id: Long, val account: String, val display: String, val isGoogleOwner: Boolean)

    /** 쓰기 가능 + 화면 표시 캘린더 전체. */
    fun writableCalendars(ctx: Context): List<CalInfo> {
        if (!hasPermission(ctx)) return emptyList()
        val proj = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.ACCOUNT_NAME,
            CalendarContract.Calendars.ACCOUNT_TYPE,
            CalendarContract.Calendars.OWNER_ACCOUNT,
            CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
        )
        val sel = "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ${CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR} " +
            "AND ${CalendarContract.Calendars.VISIBLE} = 1"
        val out = mutableListOf<CalInfo>()
        ctx.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, proj, sel, null, null)?.use { c ->
            while (c.moveToNext()) {
                val acct = c.getString(1) ?: ""
                val type = c.getString(2)
                val owner = c.getString(3)
                val disp = c.getString(4) ?: acct
                val gOwner = type == "com.google" && !owner.isNullOrBlank() && owner == acct
                out.add(CalInfo(c.getLong(0), acct, disp, gOwner))
            }
        }
        return out
    }

    /** 설정 피커용: 본인 소유 Google 캘린더만 (없으면 전체 쓰기가능). */
    fun selectableCalendars(ctx: Context): List<CalInfo> {
        val all = writableCalendars(ctx)
        return all.filter { it.isGoogleOwner }.ifEmpty { all }
    }

    /** 쓰기 대상: ① 설정에서 고른 캘린더(유효하면) ② 선호 계정 Google 소유 ③ 아무 Google 소유 ④ 첫 쓰기가능. */
    private fun primaryCalendarId(ctx: Context): Long? {
        val all = writableCalendars(ctx)
        if (all.isEmpty()) return null
        val saved = SettingsStore.from(ctx).targetCalendarId
        if (saved != -1L && all.any { it.id == saved }) return saved
        return all.firstOrNull { it.isGoogleOwner && it.account == PREFERRED_ACCOUNT }?.id
            ?: all.firstOrNull { it.isGoogleOwner }?.id
            ?: all.first().id
    }

    private fun buildDescription(event: CalendarEvent): String? {
        // 참석자는 캘린더에 넣지 않는다(사용자 운영방식 — 일정의 핵심은 활동·시간이지 참석자가 아님).
        return event.description?.takeIf { it.isNotBlank() }
    }

    /** 'YYYY-MM-DD'(또는 ...T...의 날짜부) → 그 날짜의 UTC 자정 epoch millis. 종일 일정용. */
    private fun parseDateUtc(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        return try {
            val fmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            fmt.timeZone = TimeZone.getTimeZone("UTC")
            fmt.parse(iso.substringBefore('T'))?.time
        } catch (e: Exception) {
            null
        }
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
