package com.calenda

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 캘린더용 '해석된' 일정 (DateResolver 출력). start/end는 절대 ISO, title은 조합 완료. */
data class CalendarEvent(
    val title: String,
    val start: String?,      // ISO 8601 (+09:00) 또는 YYYY-MM-DD(종일)
    val end: String?,
    val allDay: Boolean,
    val location: String?,
    val attendees: List<String>,
    val description: String?,
    val recurrence: String?, // RRULE (description에서 파싱 가능하지만 CalendarWriter에서 사용)
    val confidence: Double,
)

/** 시각 표현 {시, 분, 표시어}. 24h 변환은 DateResolver가. (schema.md time 객체) */
data class TimeOfDay(
    val hour: Int,
    val minute: Int,
    val marker: String?,     // 오전/오후/저녁/밤/낮/정오/자정 또는 null
)

/**
 * 모델이 추출한 '미해석' 일정 (플랫 스키마). DateResolver.resolveEvent로 CalendarEvent화.
 * attendees/organizer/recurrence는 description 통합 필드에 포함됨.
 */
data class ExtractedEvent(
    val title: String?,      // 메시지 자연 제목(시간 제외), null이면 일정 없음
    val date: String?,       // 상대 토큰 | "YYYY-MM-DD" | null
    val time: TimeOfDay?,
    val endTime: TimeOfDay?,
    val location: String?,
    val description: String?,  // 참석자·주최자·반복·URL 등 통합
)

/** 모델 출력 파싱 결과. 플랫 스키마 is_schedule + 단일 ExtractedEvent. */
data class Extraction(
    val isSchedule: Boolean,           // true=확정 일정, false=비일정
    val event: ExtractedEvent?,        // 추출된 필드 (is_schedule=false여도 존재 가능)
    val rawJson: String,
    val parseError: String? = null,
) {
    /** 캘린더 등록 후보 (is_schedule=true). false면 파이프라인이 드롭. */
    val detected: Boolean get() = isSchedule
}

/** 멀티턴 대화내역의 한 턴. (scripts/_common.build_user_block의 thread_context 원소와 동형) */
data class ThreadTurn(
    val time: String,    // "HH:MM"
    val sender: String,
    val message: String,
)

/**
 * 프롬프트 빌드 + 모델 호출 + JSON 파싱.
 * 학습 때와 동일한 chat 포맷(Qwen ChatML)을 사용해야 모델이 학습한 분포와 일치.
 */
object ScheduleExtractor {

    // ★ configs/model_qwen3_0_6b.yaml의 system_prompt와 글자까지 동일해야 함 (학습/추론 분포 일치).
    private const val SYSTEM_PROMPT =
        "당신은 메시지에서 일정 정보를 추출하는 모델입니다. 날짜를 계산하지 말고 표현 그대로 추출합니다.\n" +
        "date: 상대 날짜는 토큰으로(내일·모레·글피·다음주화·1주후·1개월후 등), 명시 날짜는 YYYY-MM-DD, 없으면 null.\n" +
        "time: {hour, minute, marker:null} 객체. 시각은 24시간 형식으로 직접 출력. 오후 3시→15, 저녁 7시→19, 밤 9시→21, 정오→12, 자정→0. marker는 항상 null. <대화내역>에 오전/오후 단서가 있으면 참고.\n" +
        "title에는 메시지의 일정 제목/주제를 시간 표현만 제외하고 최대한 그대로 보존합니다. 발신인 태그는 앱이 붙입니다.\n" +
        "description에는 참석자·주최자·반복일정·전화번호·URL·준비물 등 부가 정보를 통합합니다.\n" +
        "지정된 플랫 JSON 스키마에 맞춰 순수 JSON만 출력하고, 명시되지 않은 정보는 null을 씁니다.\n" +
        "<대화내역>이 있으면 맥락을 참고하되 추출 대상은 마지막 <메시지>이며, 여러 후보가 협의됐다면 가장 최근 합의값을 씁니다.\n" +
        "is_schedule은 두 질문으로 정합니다. ① 사용자 본인이 직접 갈/할 미래의 일인가? 아니면(거래·결제·배송·광고·인사·과거·남의 일정) false. ② 본인 일이면 — 나를 특정한 확정 일정(약속·회의·예약·업무 요청·합의 도달)이면 true. 공고·안내·미수락 제안이면 false. is_schedule=false여도 title/date/time/location 등 추출 가능한 필드는 채웁니다.\n"

    private val weekdaysKo = listOf("월", "화", "수", "목", "금", "토", "일")

    /** 수신시각 ISO에 한국어 요일을 덧붙임 (학습 train_lora._with_weekday와 동일 형식). */
    private fun withWeekday(receivedAt: String): String {
        return try {
            // ISO의 날짜 부분(yyyy-MM-dd)만 파싱해 요일 계산 (tz 유무 무관)
            val datePart = receivedAt.substringBefore('T').trim()
            val fmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            val d = fmt.parse(datePart) ?: return receivedAt
            val cal = java.util.Calendar.getInstance().apply { time = d }
            // Calendar.DAY_OF_WEEK: 일=1..토=7 → 월=0..일=6 인덱스로 변환
            val idx = (cal.get(java.util.Calendar.DAY_OF_WEEK) + 5) % 7
            "$receivedAt (${weekdaysKo[idx]})"
        } catch (e: Exception) {
            receivedAt
        }
    }

    /**
     * 학습/추론 공용 user 블록. scripts/_common.build_user_block과 동일 포맷이어야 한다.
     * thread가 비어있지 않으면 <발신자>와 <메시지> 사이에 <대화내역> 블록을 삽입(멀티턴),
     * 비어있으면 생략(단일 메시지) → 하위호환.
     */
    fun buildUserBlock(channel: String, receivedAt: String, sender: String,
                       message: String, thread: List<ThreadTurn> = emptyList()): String {
        val parts = mutableListOf(
            "<채널: $channel>",
            "<수신시각: ${withWeekday(receivedAt)}>",
            "<발신자: $sender>",
        )
        if (thread.isNotEmpty()) {
            val lines = thread.joinToString("\n") { "[${it.time}] ${it.sender}: ${it.message}" }
            parts.add("<대화내역>\n$lines\n</대화내역>")
        }
        parts.add("<메시지>\n$message\n</메시지>")
        return parts.joinToString("\n")
    }

    /** Qwen3 ChatML 포맷으로 프롬프트 구성. thread 지정 시 멀티턴.
     *  non-thinking: assistant 턴에 빈 <think></think>를 프리필 → 모델은 순수 JSON만 생성.
     *  (학습/eval 분포와 일치: enable_thinking=False 렌더. Qwen3 전용 — 0.5B는 미사용.) */
    fun buildPrompt(channel: String, receivedAt: String, sender: String,
                    message: String, thread: List<ThreadTurn> = emptyList()): String {
        val userBlock = buildUserBlock(channel, receivedAt, sender, message, thread)
        return buildString {
            append("<|im_start|>system\n").append(SYSTEM_PROMPT).append("<|im_end|>\n")
            append("<|im_start|>user\n").append(userBlock).append("<|im_end|>\n")
            append("<|im_start|>assistant\n<think>\n\n</think>\n\n")
        }
    }

    /** 현재 시각을 ISO 8601(기기 로컬 tz)로. */
    fun nowIso(): String = isoOf(System.currentTimeMillis())

    /** epoch millis → ISO 8601 (기기 로컬 tz). 수신시각 필드용. */
    fun isoOf(millis: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date(millis))

    /** epoch millis → "HH:mm" (기기 로컬 tz). 대화내역 시각 표기용. */
    fun clockOf(millis: Long): String =
        SimpleDateFormat("HH:mm", Locale.US).format(Date(millis))

    /** 멀티턴 대화내역 → JSON 문자열(학습 페어 thread_context 형식). 비어있으면 null. */
    fun threadToJson(thread: List<ThreadTurn>): String? {
        if (thread.isEmpty()) return null
        val arr = org.json.JSONArray()
        for (t in thread) {
            arr.put(
                org.json.JSONObject()
                    .put("time", t.time).put("sender", t.sender).put("message", t.message),
            )
        }
        return arr.toString()
    }

    /**
     * 모델 raw 출력에서 JSON 추출 + 파싱 (플랫 스키마: is_schedule + 개별 필드).
     * 구 스키마(schedule_status + events[]) 폴백도 수용해 배포본 c2v13과 호환.
     */
    fun parse(raw: String): Extraction {
        val cleaned = stripFences(raw).trim()
        return try {
            val obj = JSONObject(cleaned)

            // ── is_schedule 판정 (플랫 신규 → 구 schedule_status → 구 has_schedule 순) ──
            val isSchedule = when {
                obj.has("is_schedule") -> {
                    val v = obj.opt("is_schedule")
                    when (v) {
                        is Boolean -> v
                        is String  -> v.trim().lowercase() in listOf("true", "yes")
                        else       -> false
                    }
                }
                obj.has("schedule_status") -> {
                    obj.optString("schedule_status", "no").trim().lowercase() == "yes"
                }
                else -> obj.optBoolean("has_schedule", false)
            }

            // ── 필드 소스 결정: 플랫(최상위) 우선, 없으면 events[0] 폴백 ──
            val src: org.json.JSONObject = when {
                obj.has("title") || obj.has("date") || obj.has("time") -> obj
                obj.optJSONArray("events")?.length() ?: 0 > 0 -> obj.optJSONArray("events")!!.getJSONObject(0)
                else -> obj
            }

            val event = ExtractedEvent(
                title       = src.optStringOrNull("title"),
                date        = src.optStringOrNull("date"),
                time        = parseTimeObj(src, "time"),
                endTime     = parseTimeObj(src, "end_time"),
                location    = src.optStringOrNull("location"),
                description = buildDescription(src),
            )

            Extraction(isSchedule, event, cleaned)
        } catch (ex: Exception) {
            Extraction(false, null, cleaned, parseError = ex.message ?: "parse error")
        }
    }

    /**
     * description 필드 조합.
     * 플랫 스키마: description 그대로.
     * 구 스키마 폴백: attendees + organizer + recurrence → 한 필드로 병합.
     */
    private fun buildDescription(e: org.json.JSONObject): String? {
        val parts = mutableListOf<String>()
        e.optStringOrNull("description")?.let { parts.add(it) }
        // 구 스키마 폴백 (배포본 c2v13 호환)
        val atts = mutableListOf<String>()
        e.optJSONArray("attendees")?.let { for (i in 0 until it.length()) atts.add(it.getString(i)) }
        if (atts.isNotEmpty()) parts.add("참석자: ${atts.joinToString(", ")}")
        e.optStringOrNull("organizer")?.let { parts.add("주최: $it") }
        e.optStringOrNull("recurrence")?.let { parts.add("반복: $it") }
        return parts.joinToString("\n").ifEmpty { null }
    }

    /** time/end_time 파싱: 객체 {hour,minute,marker} 우선, "HH:MM" 문자열도 허용. */
    private fun parseTimeObj(e: JSONObject, key: String): TimeOfDay? {
        if (!e.has(key) || e.isNull(key)) return null
        e.optJSONObject(key)?.let {
            return TimeOfDay(it.optInt("hour", 0), it.optInt("minute", 0), it.optStringOrNull("marker"))
        }
        val m = Regex("^(\\d{1,2}):(\\d{2})$").find(e.optString(key, "")) ?: return null
        return TimeOfDay(m.groupValues[1].toInt(), m.groupValues[2].toInt(), null)
    }

    private fun stripFences(text: String): String {
        var t = text.trim()
        // ```json ... ``` 또는 ``` ... ``` 제거. 여러 블록이면 마지막 것.
        val regex = Regex("```(?:json)?\\s*([\\s\\S]*?)```")
        val matches = regex.findAll(t).toList()
        if (matches.isNotEmpty()) {
            return matches.last().groupValues[1].trim()
        }
        // 첫 '{' ~ 마지막 '}' 추출 (안전망)
        val s = t.indexOf('{')
        val eIdx = t.lastIndexOf('}')
        if (s >= 0 && eIdx > s) return t.substring(s, eIdx + 1)
        return t
    }

    private fun JSONObject.optStringOrNull(key: String): String? {
        if (!has(key) || isNull(key)) return null
        val v = optString(key, "")
        return v.ifEmpty { null }
    }
}
