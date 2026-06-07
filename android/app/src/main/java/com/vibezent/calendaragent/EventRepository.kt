package com.vibezent.calendaragent

import android.content.Context
import kotlinx.coroutines.flow.Flow

/**
 * 이벤트함 영속화 + 중복제거. 파이프라인(쓰기)과 UI(읽기/상태변경) 공용 진입점.
 * DB 접근을 한 곳으로 모아 호출부가 Room 디테일을 모르게 한다.
 */
class EventRepository(private val dao: EventDao) {

    val all: Flow<List<DetectedEvent>> get() = dao.observeAll()
    fun byStatus(s: EventStatus): Flow<List<DetectedEvent>> = dao.observeByStatus(s)
    fun since(ms: Long): Flow<List<DetectedEvent>> = dao.observeSince(ms)
    fun pendingCount(): Flow<Int> = dao.countByStatus(EventStatus.PENDING)

    /** 대시보드: 예비(오늘 이후 미등록) / 오늘 등록된 건. */
    fun activeCandidates(today: String): Flow<List<DetectedEvent>> = dao.observeActiveCandidates(today)
    fun registeredSince(sinceMs: Long): Flow<List<DetectedEvent>> = dao.observeRegisteredSince(sinceMs)
    suspend fun purgePastPending(today: String) = dao.purgePastPending(today)

    /**
     * 해석된 이벤트를 저장. 중복(dedupeKey)이면 null, 새로 저장되면 row id.
     * receivedAt/modelRawJson/threadJson은 incremental-learning 페어 재구성용 캡처(선택).
     */
    suspend fun save(
        ev: CalendarEvent, channel: String, sender: String, raw: String, status: EventStatus,
        receivedAt: String = "", modelRawJson: String? = null, threadJson: String? = null,
        baseTitle: String = "", room: String = "",
    ): Long? {
        // 그룹 누적 병합: 같은 채널·시작·활동(baseTitle)(+같은 방)인 최근 일정이 있으면
        // 새 카드 대신 그 일정에 참석자를 union(같은 모임에 참가자만 추가되는 카톡 패턴).
        // baseTitle은 r19 모델이 안정 출력(동기회 등) → 그 전엔 제목이 흔들려 병합이 잘 안 잡힐 수 있음.
        if (baseTitle.isNotBlank()) {
            val cand = dao.findMergeable(channel, baseTitle, ev.start, System.currentTimeMillis() - MERGE_WINDOW_MS)
            if (cand != null && roomMatches(cand.room, room)) {
                val merged = (cand.attendees + ev.attendees).filter { it.isNotBlank() }.distinct()
                if (merged.size > cand.attendees.size) {
                    // 참석자 ≥3이면 제목은 활동만(이름·출처 생략) — composeTitle 규칙과 일치.
                    val newTitle = DateResolver.composeTitle(baseTitle, merged, null, null)
                    dao.update(cand.copy(attendees = merged, title = newTitle))
                }
                return null   // 병합됨 → 새 카드/알림 없음(기존 카드가 갱신됨)
            }
        }
        val row = DetectedEvent(
            title = ev.title, start = ev.start, end = ev.end, allDay = ev.allDay,
            location = ev.location, attendees = ev.attendees, description = ev.description,
            recurrence = ev.recurrence, confidence = ev.confidence,
            channel = channel, sender = sender, rawMessage = raw,
            room = room, baseTitle = baseTitle,
            status = status, dedupeKey = dedupeKey(channel, ev, receivedAt),
            createdAt = System.currentTimeMillis(),
            receivedAt = receivedAt, modelRawJson = modelRawJson, threadJson = threadJson,
        )
        val id = dao.insertIgnore(row)
        return if (id >= 0) id else null
    }

    /** 방이름 일치 판정: 둘 다 있으면 같아야 병합, 한쪽이라도 비면 차단하지 않음(SMS·1:1 호환). */
    private fun roomMatches(a: String, b: String): Boolean =
        a.isBlank() || b.isBlank() || a == b

    suspend fun get(id: Long): DetectedEvent? = dao.getById(id)
    suspend fun update(ev: DetectedEvent) = dao.update(ev)

    /** 상태 변경. 등록(ADDED/AUTO_ADDED)으로 바뀌면 registeredAt=now, 그 외엔 null로 클리어. */
    suspend fun setStatus(id: Long, s: EventStatus, calId: Long? = null) {
        val regAt = if (s == EventStatus.ADDED || s == EventStatus.AUTO_ADDED) System.currentTimeMillis() else null
        dao.setStatus(id, s, calId, regAt)
    }
    suspend fun delete(ev: DetectedEvent) = dao.delete(ev)
    suspend fun clearDismissed() = dao.clearByStatus(EventStatus.DISMISSED)

    /** 학습 데이터 내보내기 — 신규(미전송) 후보. */
    fun newCandidateCount(): Flow<Int> = dao.observeNewCandidateCount()
    suspend fun newTrainingCandidates(): List<DetectedEvent> = dao.newTrainingCandidates()
    suspend fun markDecidedExported() = dao.markDecidedExported()

    companion object {
        /** 그룹 누적 병합 시간창(이 안의 같은 활동·시작·방을 한 일정으로). start 동일이 1차 앵커, 이건 백스톱. */
        private const val MERGE_WINDOW_MS = 30L * 24 * 60 * 60 * 1000  // 30일

        fun from(ctx: Context): EventRepository = EventRepository(AppDatabase.get(ctx).eventDao())

        /** 같은 채널·수신시각·시작시각·제목이면 동일 건으로 간주. receivedAt 포함 →
         *  다른 시각에 또 받은 같은 메시지는 별개 이벤트로 검출(알림 재게시는 동일 postTime이라 계속 억제). */
        fun dedupeKey(channel: String, ev: CalendarEvent, receivedAt: String): String =
            "$channel|$receivedAt|${ev.start ?: ""}|${ev.title.trim()}"
    }
}
