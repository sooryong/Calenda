package com.vibezent.calendaragent

/** 수집된 한 건의 수신 메시지 (카톡/문자/메일 공통). */
data class IncomingMessage(
    val channel: String,   // "kakao" | "sms" | "gmail"
    val sender: String,    // 발신자(또는 카톡 방/상대 이름)
    val body: String,
    val timeMillis: Long,
) {
    /** 같은 대화로 묶는 키. 채널+발신자(방) 기준. */
    val conversationKey: String get() = "$channel:$sender"
}

/**
 * 대화별 최근 메시지 롤링 버퍼.
 * 단일/멀티턴 판단은 별도 분류기가 아니라 "이 대화에 시간창 안의 직전 메시지가 있는가"로 결정한다.
 *   - 직전 메시지 있음 → <대화내역>으로 첨부 (멀티턴)
 *   - 없음             → 단일 메시지
 *
 * 한계: 알림/SMS는 '수신' 메시지만 관측 가능 → 내가 보낸 확정("좋아요")은 버퍼에 안 들어옴.
 *       그래도 상대의 제안/확정 맥락은 누적되므로 추출에 도움. (추후 보완 과제)
 */
object ConversationBuffer {
    private const val WINDOW_MS = 30 * 60 * 1000L   // 30분 넘은 메시지는 다른 대화로 간주
    private const val MAX_PER_CONV = 6              // 대화당 보관 상한
    private const val CONTEXT_MAX = 5               // <대화내역>에 넣을 직전 메시지 수

    private val map = HashMap<String, ArrayDeque<IncomingMessage>>()

    /** 메시지 적재 + 오래된 것/초과분 정리. 직전과 완전 동일하면 중복 알림으로 보고 무시(false 반환). */
    @Synchronized
    fun add(msg: IncomingMessage): Boolean {
        val dq = map.getOrPut(msg.conversationKey) { ArrayDeque() }
        // 시간창 밖(오래된) 메시지 제거
        while (dq.isNotEmpty() && msg.timeMillis - dq.first().timeMillis > WINDOW_MS) dq.removeFirst()
        // 동일 본문 연속 중복(알림 재게시 등) 방지
        if (dq.isNotEmpty() && dq.last().body == msg.body && dq.last().sender == msg.sender) return false
        dq.addLast(msg)
        while (dq.size > MAX_PER_CONV) dq.removeFirst()
        return true
    }

    /** 해당 대화의 '직전' 메시지들(현재 메시지 제외)을 <대화내역>용 턴으로 반환. 없으면 빈 리스트=단일. */
    @Synchronized
    fun contextBefore(key: String): List<ThreadTurn> {
        val dq = map[key] ?: return emptyList()
        if (dq.size <= 1) return emptyList()
        return dq.toList().dropLast(1)             // 마지막=현재 메시지 제외
            .takeLast(CONTEXT_MAX)
            .map { ThreadTurn(ScheduleExtractor.clockOf(it.timeMillis), it.sender, it.body) }
    }
}
