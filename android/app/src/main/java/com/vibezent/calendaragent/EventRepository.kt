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
    ): Long? {
        val row = DetectedEvent(
            title = ev.title, start = ev.start, end = ev.end, allDay = ev.allDay,
            location = ev.location, attendees = ev.attendees, description = ev.description,
            recurrence = ev.recurrence, confidence = ev.confidence,
            channel = channel, sender = sender, rawMessage = raw,
            status = status, dedupeKey = dedupeKey(channel, ev),
            createdAt = System.currentTimeMillis(),
            receivedAt = receivedAt, modelRawJson = modelRawJson, threadJson = threadJson,
        )
        val id = dao.insertIgnore(row)
        return if (id >= 0) id else null
    }

    suspend fun get(id: Long): DetectedEvent? = dao.getById(id)
    suspend fun update(ev: DetectedEvent) = dao.update(ev)

    /** 상태 변경. 등록(ADDED/AUTO_ADDED)으로 바뀌면 registeredAt=now, 그 외엔 null로 클리어. */
    suspend fun setStatus(id: Long, s: EventStatus, calId: Long? = null) {
        val regAt = if (s == EventStatus.ADDED || s == EventStatus.AUTO_ADDED) System.currentTimeMillis() else null
        dao.setStatus(id, s, calId, regAt)
    }
    suspend fun delete(ev: DetectedEvent) = dao.delete(ev)
    suspend fun clearDismissed() = dao.clearByStatus(EventStatus.DISMISSED)
    suspend fun trainingCandidates(): List<DetectedEvent> = dao.trainingCandidates()

    companion object {
        fun from(ctx: Context): EventRepository = EventRepository(AppDatabase.get(ctx).eventDao())

        /** 같은 채널·시작시각·제목이면 동일 일정으로 간주(중복 알림/재추출 억제). */
        fun dedupeKey(channel: String, ev: CalendarEvent): String =
            "$channel|${ev.start ?: ""}|${ev.title.trim()}"
    }
}
