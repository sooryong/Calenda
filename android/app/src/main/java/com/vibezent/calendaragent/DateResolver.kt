package com.vibezent.calendaragent

import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime

/**
 * 모델이 추출한 date/time 토큰 → 절대 시각 + 캘린더용 이벤트.
 * ★ scripts/_common.py 의 resolve_date / resolve_time / resolve_when / compose_title / resolve_event 와
 *   동일 규칙(=schema.md 어휘·변환 표)이어야 한다. 한쪽 바꾸면 양쪽 같이.
 */
object DateResolver {

    private val WD = "월화수목금토일"

    /** 수신시각 문자열 → LocalDateTime (tz 무시한 로컬 시계). 파싱 실패 시 null. */
    private fun parseReceived(s: String): LocalDateTime? = try {
        OffsetDateTime.parse(s).toLocalDateTime()
    } catch (e: Exception) {
        try {
            LocalDateTime.parse(s)
        } catch (e2: Exception) {
            try { LocalDate.parse(s.substringBefore('T')).atStartOfDay() } catch (e3: Exception) { null }
        }
    }

    /** date 토큰 → 절대 LocalDate. 인식 못 하면 null. */
    fun resolveDate(r: LocalDate, token: String?): LocalDate? {
        if (token.isNullOrBlank()) return null
        when (token) {
            "오늘" -> return r
            "내일" -> return r.plusDays(1)
            "모레" -> return r.plusDays(2)
            "글피" -> return r.plusDays(3)
        }
        Regex("^(\\d+)일후$").find(token)?.let { return r.plusDays(it.groupValues[1].toLong()) }
        Regex("^(\\d+)주후$").find(token)?.let { return r.plusDays(7L * it.groupValues[1].toLong()) }
        Regex("^(\\d+)개월후$").find(token)?.let { return r.plusMonths(it.groupValues[1].toLong()) }
        Regex("^(\\d+)년후$").find(token)?.let { return r.plusYears(it.groupValues[1].toLong()) }
        Regex("^(이번주|다음주|다다음주)([월화수목금토일])$").find(token)?.let {
            val weeks = mapOf("이번주" to 0L, "다음주" to 1L, "다다음주" to 2L)[it.groupValues[1]]!!
            val monday = r.minusDays((r.dayOfWeek.value - 1).toLong()).plusWeeks(weeks)
            return monday.plusDays(WD.indexOf(it.groupValues[2]).toLong())
        }
        if (token == "이번주말" || token == "다음주말") {
            val toSat = ((6 - r.dayOfWeek.value) % 7 + 7) % 7   // 다가오는 토요일까지 일수
            val sat = r.plusDays(toSat.toLong())
            return if (token == "다음주말") sat.plusWeeks(1) else sat
        }
        if (Regex("^\\d{4}-\\d{2}-\\d{2}$").matches(token)) {
            return try { LocalDate.parse(token) } catch (e: Exception) { null }
        }
        return null
    }

    /** time {hour,minute,marker} → "HH:MM"(24h). null이면 null. */
    fun resolveTime(t: TimeOfDay?, received: LocalDateTime): String? {
        if (t == null) return null
        var h = t.hour
        var m = t.minute
        when (t.marker) {
            "오후", "저녁", "밤", "낮" -> if (h < 12) h += 12
            "오전", "아침", "새벽" -> if (h == 12) h = 0
            "정오" -> { h = 12; m = 0 }
            "자정" -> { h = 0; m = 0 }
            null -> if (h in 1..12) {                       // 표시어 없는 1~12시: 받은시각 이후 가장 가까운 쪽
                val am = h % 12
                val pm = h % 12 + 12
                val rh = received.hour + received.minute / 60.0
                h = listOf(am, pm).sorted().firstOrNull { it >= rh } ?: pm
            }
        }
        return "%02d:%02d".format(h, m)
    }

    data class Resolved(val start: String?, val end: String?, val allDay: Boolean)

    /** date/time 토큰 → 절대 start/end ISO (+09:00). */
    fun resolveWhen(receivedAt: String, date: String?, time: TimeOfDay?,
                    endTime: TimeOfDay?, allDay: Boolean): Resolved {
        val recv = parseReceived(receivedAt) ?: return Resolved(null, null, allDay)
        var d = resolveDate(recv.toLocalDate(), date)
        if (d == null && time != null) d = recv.toLocalDate()       // 규칙7: 날짜 없고 시간만 → 오늘
        if (d == null) return Resolved(null, null, allDay)
        if (allDay || time == null) return Resolved(d.toString(), null, allDay)
        val start = "${d}T${resolveTime(time, recv)}:00+09:00"
        val end = endTime?.let { "${d}T${resolveTime(it, recv)}:00+09:00" }
        return Resolved(start, end, false)
    }

    private fun gwa(word: String): String {
        val ch = word.lastOrNull() ?: return "와"
        if (ch in '가'..'힣') return if ((ch.code - 0xAC00) % 28 != 0) "과" else "와"
        return "와"
    }

    /** 캘린더 표시 제목 조합: 누구와 + 활동 + ` · 발신자(소속)`. (_common.compose_title 미러) */
    fun composeTitle(baseTitle: String?, attendees: List<String>, organizer: String?, sender: String?): String {
        var title = (baseTitle ?: "일정").trim()
        val who = attendees.filter { it.isNotBlank() && !title.contains(it) }
        if (who.isNotEmpty()) {
            val joined = who.joinToString(", ")
            title = "$joined${gwa(joined)} $title"
        }
        var src: String? = null
        if (!sender.isNullOrBlank() && sender !in listOf("나", "Me", "me")) {
            val s = sender.replace("[Web발신]", "").trim()
            src = when {
                !organizer.isNullOrBlank() && !s.contains(organizer) -> "$s ($organizer)"
                !organizer.isNullOrBlank() -> organizer
                else -> s
            }
        } else if (!organizer.isNullOrBlank()) {
            src = organizer
        }
        if (src != null && !title.contains(src)) title = "$title · $src"
        return title
    }

    /** 모델 추출 이벤트 → 캘린더용 CalendarEvent (시각 변환 + 제목 조합 + 장소 등 보존). */
    fun resolveEvent(receivedAt: String, sender: String?, ev: ExtractedEvent): CalendarEvent {
        val w = resolveWhen(receivedAt, ev.date, ev.time, ev.endTime, ev.allDay)
        return CalendarEvent(
            title = composeTitle(ev.title, ev.attendees, ev.organizer, sender),
            start = w.start,
            end = w.end,
            allDay = w.allDay,
            location = ev.location,
            attendees = ev.attendees,
            description = ev.description,
            recurrence = ev.recurrence,
            confidence = ev.confidence,
        )
    }
}
