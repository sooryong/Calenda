package com.calenda

import java.util.Calendar

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
            "\\d{1,2}\\s*시", "\\d{1,2}:\\d{2}", "\\d{1,2}\\s*일", "\\d{1,2}/\\d{1,2}",
            "\\d+\\s*(주|개월|달|년)\\s*(뒤|후)",
            "약속", "회의", "미팅", "예약", "모임", "일정", "스케줄", "만나", "보자", "봬요",
            "meeting", "appointment", "schedule", "tomorrow", "am", "pm",
        ).joinToString("|"),
        RegexOption.IGNORE_CASE,
    )

    // 결제일시 패턴: "2026.06.20 21:27" 또는 "06/20 21:27"
    private val PAYMENT_DATETIME = Regex(
        """(?:(\d{4})[./](\d{2})[./](\d{2})|(\d{2})/(\d{2}))\s+(\d{2}):(\d{2})"""
    )

    private val PAYMENT_KEYWORDS = Regex(
        "결제일시|승인번호|결제[가이]\\s*(완료|취소)|충전[이가]\\s*완료|입금|출금|잔액|승인|카카오뱅크|카카오페이|국민카드|신한카드|삼성카드|현대카드|하나카드|롯데카드|농협|우리은행|케이뱅크|토스"
    )

    // 과거형 완료·상태 알림 — "~되었어요", "~됐어요", "~되었습니다", "~됐습니다" 형태
    private val COMPLETION_PAST = Regex(
        "완료됐|완료되었|복원됐|복원되었|취소됐|취소되었|처리됐|처리되었|" +
        "발송됐|발송되었|충전됐|충전되었|출금됐|출금되었|입금됐|입금되었|" +
        "승인됐|승인되었|등록됐|등록되었|확인됐|확인되었|변경됐|변경되었|" +
        "발급됐|발급되었|해지됐|해지되었|정지됐|정지되었|차단됐|차단되었"
    )

    fun looksScheduleRelated(text: String): Boolean = HINTS.containsMatchIn(text)

    /**
     * 과거형 완료·상태 알림 판별.
     * "결제가 완료되었어요", "잔액이 복원되었어요" 등은 이미 일어난 사건 — 일정 아님.
     * 단독 조건으로 차단(결제 키워드 없이도 적용).
     */
    fun isCompletionNotification(text: String): Boolean = COMPLETION_PAST.containsMatchIn(text)

    /**
     * 결제/거래 완료 알림 판별.
     * 결제 키워드가 있고 메시지 안 타임스탬프가 수신 당일이면 → 완료된 거래 알림.
     * (같은 날이기만 해도 충분 — 미래 결제 예정 알림은 날짜가 다르므로 통과)
     */
    fun isPaymentNotification(text: String, receivedMillis: Long): Boolean {
        if (!PAYMENT_KEYWORDS.containsMatchIn(text)) return false
        val match = PAYMENT_DATETIME.find(text) ?: return false

        val recvCal = Calendar.getInstance().apply { timeInMillis = receivedMillis }
        val recvYear  = recvCal.get(Calendar.YEAR)
        val recvMonth = recvCal.get(Calendar.MONTH) + 1
        val recvDay   = recvCal.get(Calendar.DAY_OF_MONTH)

        val fullYear  = match.groupValues[1].toIntOrNull()
        val fullMonth = match.groupValues[2].toIntOrNull()
        val fullDay   = match.groupValues[3].toIntOrNull()

        return if (fullYear != null && fullMonth != null && fullDay != null) {
            fullYear == recvYear && fullMonth == recvMonth && fullDay == recvDay
        } else {
            val mmMonth = match.groupValues[4].toIntOrNull() ?: return false
            val mmDay   = match.groupValues[5].toIntOrNull() ?: return false
            mmMonth == recvMonth && mmDay == recvDay
        }
    }
}
