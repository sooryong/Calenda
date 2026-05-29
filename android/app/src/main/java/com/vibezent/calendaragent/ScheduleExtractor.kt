package com.vibezent.calendaragent

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 추출된 단일 일정. */
data class CalendarEvent(
    val title: String,
    val start: String?,      // ISO 8601 (tz 있을 수도, 없으면 기기 로컬 가정)
    val end: String?,
    val allDay: Boolean,
    val location: String?,
    val attendees: List<String>,
    val description: String?,
    val recurrence: String?, // RRULE
    val confidence: Double,
)

/** 모델 출력 파싱 결과. */
data class Extraction(
    val hasSchedule: Boolean,
    val events: List<CalendarEvent>,
    val rawJson: String,
    val parseError: String? = null,
)

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

    // ★ configs/model_qwen.yaml의 system_prompt와 글자까지 동일해야 함 (학습/추론 분포 일치).
    //   YAML 블록 스칼라(|)라 줄바꿈 보존 + 끝에 개행 1개. 아래도 동일하게 맞춤.
    private const val SYSTEM_PROMPT =
        "당신은 메시지에서 일정 정보를 추출하는 모델입니다.\n" +
        "입력의 <수신시각>을 기준으로 상대 시간을 절대 시각으로 변환하고,\n" +
        "지정된 JSON 스키마에 맞춰 순수 JSON만 출력합니다.\n" +
        "메시지에 명시되지 않은 정보는 절대 만들어내지 않고 null을 씁니다.\n" +
        "<대화내역>이 있으면 그 맥락을 참고하되 추출 대상은 마지막 <메시지>이며,\n" +
        "여러 후보가 협의됐다면 가장 최근에 합의된 시각·장소를 사용합니다.\n" +
        "최종 메시지가 확정이 아니라 새 제안·유보면 has_schedule을 false로 둡니다.\n"

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

    /** Qwen2.5 ChatML 포맷으로 프롬프트 구성. thread 지정 시 멀티턴. */
    fun buildPrompt(channel: String, receivedAt: String, sender: String,
                    message: String, thread: List<ThreadTurn> = emptyList()): String {
        val userBlock = buildUserBlock(channel, receivedAt, sender, message, thread)
        return buildString {
            append("<|im_start|>system\n").append(SYSTEM_PROMPT).append("<|im_end|>\n")
            append("<|im_start|>user\n").append(userBlock).append("<|im_end|>\n")
            append("<|im_start|>assistant\n")
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

    /** 모델 raw 출력에서 JSON 추출 + 파싱. 코드펜스 있으면 제거. */
    fun parse(raw: String): Extraction {
        val cleaned = stripFences(raw).trim()
        return try {
            val obj = JSONObject(cleaned)
            val hasSchedule = obj.optBoolean("has_schedule", false)
            val events = mutableListOf<CalendarEvent>()
            val arr = obj.optJSONArray("events")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val e = arr.getJSONObject(i)
                    val attArr = e.optJSONArray("attendees")
                    val attendees = mutableListOf<String>()
                    if (attArr != null) for (j in 0 until attArr.length()) attendees.add(attArr.getString(j))
                    events.add(
                        CalendarEvent(
                            title = e.optString("title", ""),
                            start = e.optStringOrNull("start"),
                            end = e.optStringOrNull("end"),
                            allDay = e.optBoolean("all_day", false),
                            location = e.optStringOrNull("location"),
                            attendees = attendees,
                            description = e.optStringOrNull("description"),
                            recurrence = e.optStringOrNull("recurrence"),
                            confidence = e.optDouble("confidence", 0.0),
                        )
                    )
                }
            }
            Extraction(hasSchedule, events, cleaned)
        } catch (ex: Exception) {
            Extraction(false, emptyList(), cleaned, parseError = ex.message ?: "parse error")
        }
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
