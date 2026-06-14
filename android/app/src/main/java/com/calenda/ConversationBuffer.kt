package com.calenda

/** 수집된 한 건의 메시지 (카톡/문자/메일 공통). 접근성 캡처는 내 송신도 포함. */
data class IncomingMessage(
    val channel: String,   // "kakao" | "sms" | "gmail"
    val sender: String,    // 발신자. 내 송신(fromMe)이면 "나"(학습 thread_context 규칙).
    val body: String,
    val timeMillis: Long,
    val room: String = "", // 카톡 그룹 방이름(best-effort). 그룹 대화 묶음·누적 병합 보조.
    val fromMe: Boolean = false,   // 접근성 캡처에서 '내가 보낸' 말풍선이면 true.
    val counterpart: String = "",  // 상대(방 제목). 내 송신이 트리거일 때 제목 출처로 사용.
) {
    /** 같은 대화로 묶는 키. 방이 있으면 방 기준(그룹 누적이 한 대화로 묶임), 없으면 발신자. */
    val conversationKey: String get() = if (room.isNotBlank()) "$channel:room:$room" else "$channel:$sender"
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
    private const val DUP_WINDOW_MS = 10 * 1000L    // 동일 본문 '재게시' 판정 창(이 안이면 중복, 넘으면 재수신=별건)
    private const val MAX_PER_CONV = 6              // 대화당 보관 상한
    private const val CONTEXT_MAX = 5               // <대화내역>에 넣을 직전 메시지 수

    private val map = HashMap<String, ArrayDeque<IncomingMessage>>()

    /** 메시지 적재 + 오래된 것/초과분 정리. 직전과 완전 동일하면 중복 알림으로 보고 무시(false 반환). */
    @Synchronized
    fun add(msg: IncomingMessage): Boolean {
        val dq = map.getOrPut(msg.conversationKey) { ArrayDeque() }
        // 시간창 밖(오래된) 메시지 제거
        while (dq.isNotEmpty() && msg.timeMillis - dq.first().timeMillis > WINDOW_MS) dq.removeFirst()
        // 동일 본문 '연속 + 짧은 시간 내' 중복(알림 재게시 등)만 무시.
        // 다른 시각에 또 받은 같은 문자는 별개 수신이므로 통과시킨다.
        val last = dq.lastOrNull()
        if (last != null && last.body == msg.body && last.sender == msg.sender &&
            msg.timeMillis - last.timeMillis < DUP_WINDOW_MS) return false
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
