package com.vibezent.calendaragent

/**
 * 온디바이스 LLM을 매 메시지마다 돌리면 배터리 부담이 크다.
 * 일정 관련 단서(시간/날짜/요일/약속류 키워드)가 있는 메시지만 추론하도록 거르는 값싼 사전 필터.
 * 재현율 우선(애매하면 통과) — 정밀도는 모델의 has_schedule 판단에 맡긴다.
 */
object ScheduleHeuristics {

    private val HINTS = Regex(
        listOf(
            "내일", "모레", "글피", "오늘", "다음\\s*주", "이번\\s*주", "주말",
            "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
            "오전", "오후", "저녁", "정오", "새벽", "아침", "낮",
            "\\d{1,2}\\s*시", "\\d{1,2}:\\d{2}", "\\d{1,2}\\s*월\\s*\\d{1,2}\\s*일", "\\d{1,2}/\\d{1,2}",
            "약속", "회의", "미팅", "예약", "모임", "일정", "스케줄", "만나", "보자", "봬요",
            "meeting", "appointment", "schedule", "tomorrow", "am", "pm",
        ).joinToString("|"),
        RegexOption.IGNORE_CASE,
    )

    fun looksScheduleRelated(text: String): Boolean = HINTS.containsMatchIn(text)
}
