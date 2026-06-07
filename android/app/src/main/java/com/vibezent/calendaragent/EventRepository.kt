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
        // 번호목록 참석자를 앱이 결정론적으로 보강(0.5B가 리스트를 끝까지 못 읽음). 모델 attendees와 union.
        val roster = DateResolver.parseRoster(raw)
        val effAttendees = (ev.attendees + roster).filter { it.isNotBlank() }.distinct()
        // roster가 더 채웠으면 제목 재조합(≥3이면 활동만). baseTitle 없으면 원 제목 유지.
        val effTitle = if (roster.isNotEmpty() && baseTitle.isNotBlank())
            DateResolver.composeTitle(baseTitle, effAttendees, null, sender)
        else ev.title
        val since = System.currentTimeMillis() - MERGE_WINDOW_MS

        // 그룹 누적 병합 — 같은 모임에 참가자만 추가되는 카톡 패턴을 한 일정으로(+참석자 union).
        // 1순위: 방-인지 (채널+방+시작). 제목이 메시지마다 흔들려도 한 일정으로 묶음.
        if (room.isNotBlank()) {
            dao.findMergeableByRoom(channel, room, ev.start, since)?.let {
                mergeInto(it, baseTitle); return null
            }
        }
        // 2순위: 방 없음/1:1 — (채널+시작+활동). 같은 활동·시작이면 합침(SMS 재수신 등도 단일화).
        if (baseTitle.isNotBlank()) {
            dao.findMergeable(channel, baseTitle, ev.start, since)?.let {
                if (roomMatches(it.room, room)) { mergeInto(it, baseTitle); return null }
            }
        }

        val row = DetectedEvent(
            title = effTitle, start = ev.start, end = ev.end, allDay = ev.allDay,
            location = ev.location, attendees = effAttendees, description = ev.description,
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

    /** 같은 모임의 후속 메시지 처리. **참가자만 바뀌면 일정은 그대로 둔다**(참석자는 일정 핵심이 아님).
     *  단, 더 충실한 활동 제목이 오면 제목만 보정한다(예: '기타 회의'→'동기회'). */
    private suspend fun mergeInto(cand: DetectedEvent, newBase: String) {
        val bestBase = pickBase(cand.baseTitle, newBase)
        if (bestBase != cand.baseTitle && bestBase.isNotBlank()) {
            val title = DateResolver.composeTitle(bestBase, cand.attendees, null, null)
            dao.update(cand.copy(baseTitle = bestBase, title = title))
        }
        // 그 외(참가자만 추가/변경, 동일 활동) → 변경 없음.
    }

    /** 두 활동 제목 중 더 충실한 쪽. 일반어(기타 회의 등)보다 구체어를 선호. */
    private fun pickBase(a: String, b: String): String {
        val generic = setOf("기타 회의", "회의", "협의", "일정", "기타", "미팅", "스레드 협의", "기한 회의", "약속")
        return when {
            b.isBlank() -> a
            a.isBlank() -> b
            a in generic && b !in generic -> b
            else -> a
        }
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
