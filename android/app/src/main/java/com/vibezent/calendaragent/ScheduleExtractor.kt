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

/**
 * 프롬프트 빌드 + 모델 호출 + JSON 파싱.
 * 학습 때와 동일한 chat 포맷(Qwen ChatML)을 사용해야 모델이 학습한 분포와 일치.
 */
object ScheduleExtractor {

    private const val SYSTEM_PROMPT =
        "당신은 메시지에서 일정 정보를 추출하는 모델입니다. " +
        "입력의 <수신시각>을 기준으로 상대 시간을 절대 시각으로 변환하고, " +
        "지정된 JSON 스키마에 맞춰 순수 JSON만 출력합니다. " +
        "메시지에 명시되지 않은 정보는 절대 만들어내지 않고 null을 씁니다."

    /** Qwen2.5 ChatML 포맷으로 프롬프트 구성. */
    fun buildPrompt(channel: String, receivedAt: String, sender: String, message: String): String {
        val userBlock = buildString {
            append("<채널: ").append(channel).append(">\n")
            append("<수신시각: ").append(receivedAt).append(">\n")
            append("<발신자: ").append(sender).append(">\n")
            append("<메시지>\n").append(message).append("\n</메시지>")
        }
        return buildString {
            append("<|im_start|>system\n").append(SYSTEM_PROMPT).append("<|im_end|>\n")
            append("<|im_start|>user\n").append(userBlock).append("<|im_end|>\n")
            append("<|im_start|>assistant\n")
        }
    }

    /** 현재 시각을 KST ISO 8601로 (수신시각 디폴트용). */
    fun nowIso(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
        return fmt.format(Date())
    }

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
