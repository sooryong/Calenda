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

    // 모델이 가끔 내는 영어/별칭 → 한국어 토큰 (scripts/_common._DATE_ALIAS와 동일)
    private val DATE_ALIAS = mapOf(
        "today" to "오늘", "tomorrow" to "내일", "day after tomorrow" to "모레",
        "overmorrow" to "모레", "next week" to "다음주",
        "this weekend" to "이번주말", "next weekend" to "다음주말",
    )

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

    /** date 토큰 → 절대 LocalDate. 인식 못 하면 null. 영어 별칭·공백 방어 포함. */
    fun resolveDate(r: LocalDate, token: String?): LocalDate? {
        if (token.isNullOrBlank()) return null
        var t = token.trim()
        t = (DATE_ALIAS[t.lowercase()] ?: t).replace(" ", "")
        // 요일 별칭: '이번목요일'/'이번주목요일'/'다음금요일' → '이번주목'/'다음주금'
        t = Regex("(이번|다음|다다음)주?([월화수목금토일])요일").replace(t) {
            "${it.groupValues[1]}주${it.groupValues[2]}"
        }
        when (t) {
            "오늘" -> return r
            "내일" -> return r.plusDays(1)
            "모레" -> return r.plusDays(2)
            "글피" -> return r.plusDays(3)
        }
        Regex("^(\\d+)일후$").find(t)?.let { return r.plusDays(it.groupValues[1].toLong()) }
        Regex("^(\\d+)주후$").find(t)?.let { return r.plusDays(7L * it.groupValues[1].toLong()) }
        Regex("^(\\d+)개월후$").find(t)?.let { return r.plusMonths(it.groupValues[1].toLong()) }
        Regex("^(\\d+)년후$").find(t)?.let { return r.plusYears(it.groupValues[1].toLong()) }
        if (t == "다음주" || t == "다다음주") {                  // 요일 없는 다음주 → 주 단위
            return r.plusWeeks(if (t == "다다음주") 2L else 1L)
        }
        Regex("^(이번주|다음주|다다음주)([월화수목금토일])$").find(t)?.let {
            val weeks = mapOf("이번주" to 0L, "다음주" to 1L, "다다음주" to 2L)[it.groupValues[1]]!!
            val monday = r.minusDays((r.dayOfWeek.value - 1).toLong()).plusWeeks(weeks)
            return monday.plusDays(WD.indexOf(it.groupValues[2]).toLong())
        }
        Regex("^([월화수목금토일])요일$").find(t)?.let {     // 접두사 없는 맨 요일 → 다가오는 그 요일(오늘 포함)
            val ahead = ((WD.indexOf(it.groupValues[1]) - (r.dayOfWeek.value - 1)) % 7 + 7) % 7
            return r.plusDays(ahead.toLong())
        }
        if (t == "이번주말" || t == "다음주말") {
            val toSat = ((6 - r.dayOfWeek.value) % 7 + 7) % 7   // 다가오는 토요일까지 일수
            val sat = r.plusDays(toSat.toLong())
            return if (t == "다음주말") sat.plusWeeks(1) else sat
        }
        Regex("^(\\d{1,2})일$").find(t)?.let {          // 단독 일자 → 가까운 미래 N일
            val n = it.groupValues[1].toInt()
            var cand = r.withDayOfMonth(minOf(n, r.lengthOfMonth()))
            if (cand.isBefore(r)) {
                val nm = r.plusMonths(1)
                cand = nm.withDayOfMonth(minOf(n, nm.lengthOfMonth()))
            }
            return cand
        }
        Regex("^(\\d{1,2})[월/](\\d{1,2})일?$").find(t)?.let {   // 월-일 명시: 6월16일 / 6/16 → 가까운 미래(연도 추론)
            val mo = it.groupValues[1].toInt()
            val d = it.groupValues[2].toInt()
            if (mo in 1..12 && d in 1..31) {
                var cand = LocalDate.of(r.year, mo, minOf(d, java.time.YearMonth.of(r.year, mo).lengthOfMonth()))
                if (cand.isBefore(r)) {
                    val ny = r.year + 1
                    cand = LocalDate.of(ny, mo, minOf(d, java.time.YearMonth.of(ny, mo).lengthOfMonth()))
                }
                return cand
            }
        }
        // 절대일자: 구분자(- / .) · 비패딩 모두 허용 → 2026-06-11 / 2026-6-11 / 2026/6/11 / 2025.12.3(.)
        Regex("^(\\d{4})[-/.](\\d{1,2})[-/.](\\d{1,2})\\.?$").find(t)?.let {
            val y = it.groupValues[1].toInt(); val mo = it.groupValues[2].toInt(); val d = it.groupValues[3].toInt()
            if (mo in 1..12 && d in 1..31) {
                return LocalDate.of(y, mo, minOf(d, java.time.YearMonth.of(y, mo).lengthOfMonth()))
            }
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
        // 규칙7: 날짜가 '진짜 없을' 때만 시간만 → 오늘. 인식 못 한 토큰이면 today 단정 안 함.
        if (d == null && time != null && date.isNullOrBlank()) d = recv.toLocalDate()
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

    /** 전화번호/이메일형 발신자인가(제목 출처로 부적합). (_common._is_machine_sender 미러) */
    private fun isMachineSender(sender: String?): Boolean {
        val s = (sender ?: "").replace("[Web발신]", "").trim()
        if (s.contains("@")) return true
        val digits = s.replace(Regex("[\\s\\-+()]"), "")
        return digits.isNotEmpty() && digits.all { it.isDigit() } && digits.length >= 7
    }

    private val ROSTER_STOP = setOf("참석", "회의", "모임", "일정", "확인", "참석자", "명단")

    /** 메시지의 번호목록('1. 이름' / '1.이름 2.이름')에서 사람 이름을 추출. 그룹 참석자 누적용.
     *  0.5B가 리스트를 끝까지 못 읽으므로(3~4명 중 2명) 앱이 결정론적으로 뽑는다. 앱 전용(미러 없음). */
    fun parseRoster(message: String?): List<String> {
        if (message.isNullOrBlank()) return emptyList()
        val re = Regex("""\d{1,2}\s*[.)]\s*([가-힣]{2,5}|[A-Za-z][A-Za-z ]{1,14})""")
        val out = ArrayList<String>()
        for (m in re.findAll(message)) {
            val name = m.groupValues[1].trim()
            if (name.isNotEmpty() && name !in ROSTER_STOP && name !in out) out.add(name)
        }
        return out
    }

    /** 카톡 표시명 '이름 소속 …' → (이름, 소속). 단일 토큰이면 (이름, null). (_common._split_sender 미러) */
    private fun splitSender(sender: String?): Pair<String?, String?> {
        val s = (sender ?: "").replace("[Web발신]", "").trim()
        if (s.isEmpty()) return Pair(null, null)
        val toks = s.split(Regex("\\s+"))
        return Pair(toks[0], if (toks.size > 1) toks[1] else null)
    }

    /** 캘린더 표시 제목 조합. (_common.compose_title 미러)
     *  형식: '[참석자와/과] 활동(발신자[/소속])'. 참석자 여럿은 '·'(공백 없음)로 연결.
     *  · 발신자==상대방(참석자): 접두 빼고 `활동(이름/소속)`  예 '화상미팅(정원구/페테리안)'
     *  · 참석자≠발신자: `참석자와 활동(발신자)`             예 '민지와 저녁식사(박팀장)'
     *  · 그룹(3명↑): 접두 생략, `동기회(...)`. 전화/이메일/'나' 발신자는 출처 생략. */
    fun composeTitle(baseTitle: String?, attendees: List<String>, organizer: String?, sender: String?): String {
        var title = (baseTitle ?: "일정").trim()
        // 발신자 이름/소속 분리 (사람 발신만)
        var sname: String? = null
        var saffil: String? = null
        if (!sender.isNullOrBlank() && sender !in listOf("나", "Me", "me") && !isMachineSender(sender)) {
            val p = splitSender(sender); sname = p.first; saffil = p.second
        }
        val sn = sname
        // '누구와' 접두 = 발신자 본인 아닌 참석자만; 그룹 판정은 (발신자 제외 전) 전체 인원 기준
        val allWho = attendees.filter { it.isNotBlank() && !title.contains(it) }
        val isGroup = allWho.size >= 3
        val who = allWho.filter { a -> sn == null || !(a == sn || sn.contains(a) || a.contains(sn)) }
        if (who.isNotEmpty() && !isGroup) {
            val joined = who.joinToString("·")                // 참석자 여럿 → 공백 없는 가운뎃점
            title = "$joined${gwa(joined)} $title"
        }
        // 출처(보낸사람[/소속]) → 활동 뒤 괄호로
        var inner: String? = null
        if (sn != null) {
            val org = organizer
            inner = when {
                !org.isNullOrBlank() && !sn.contains(org) -> "$sn/$org"
                !org.isNullOrBlank() -> org
                !saffil.isNullOrBlank() -> "$sn/$saffil"
                else -> sn
            }
        } else if (!organizer.isNullOrBlank()) {
            inner = organizer
        }
        val inr = inner
        if (inr != null && !title.contains(inr)) title = "$title($inr)"
        return title
    }

    /** 사람 이름이 장소로 오추출된 경우 제거. location이 참석자 이름의 일부(또는 그 반대)면
     *  사람≠장소이므로 null. 예: '정원구' ⊂ '정원구 대표' → null ('구' 행정구역 접미사 오인).
     *  (_common._drop_personlike_location 미러 — 둘을 함께 바꿔야 함.) */
    fun dropPersonlikeLocation(location: String?, attendees: List<String>): String? {
        val loc = location?.trim() ?: return location
        if (loc.length < 2 || attendees.isEmpty()) return location
        for (a in attendees) {
            val name = a.trim()
            if (name.isNotEmpty() && (name.contains(loc) || loc.contains(name))) return null
        }
        return location
    }

    /** 모델 추출 이벤트 → 캘린더용 CalendarEvent (시각 변환 + 제목 조합 + 장소 등 보존). */
    fun resolveEvent(receivedAt: String, sender: String?, ev: ExtractedEvent): CalendarEvent {
        val w = resolveWhen(receivedAt, ev.date, ev.time, ev.endTime, ev.allDay)
        return CalendarEvent(
            title = composeTitle(ev.title, ev.attendees, ev.organizer, sender),
            start = w.start,
            end = w.end,
            allDay = w.allDay,
            location = dropPersonlikeLocation(ev.location, ev.attendees),
            attendees = ev.attendees,
            description = ev.description,
            recurrence = ev.recurrence,
            confidence = ev.confidence,
        )
    }
}
