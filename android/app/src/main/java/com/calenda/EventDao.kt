package com.calenda

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

/** 이벤트함 DAO. 목록은 Flow로 관찰(UI 자동 갱신), 변경은 suspend. */
@Dao
interface EventDao {

    /** 중복(dedupeKey 유니크)이면 무시. 새로 들어가면 rowId, 무시되면 -1. */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIgnore(event: DetectedEvent): Long

    // 이벤트함 = 모든 이벤트(메인에서 '삭제'로 숨긴 DISMISSED 포함). 완전 삭제는 이벤트함 [삭제]가 DB에서 제거.
    @Query("SELECT * FROM detected_events ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<DetectedEvent>>

    @Query("SELECT * FROM detected_events WHERE status = :status ORDER BY createdAt DESC")
    fun observeByStatus(status: EventStatus): Flow<List<DetectedEvent>>

    /** 특정 시각 이후 감지분 (대시보드 '오늘' 필터용). */
    @Query("SELECT * FROM detected_events WHERE createdAt >= :since ORDER BY createdAt DESC")
    fun observeSince(since: Long): Flow<List<DetectedEvent>>

    @Query("SELECT COUNT(*) FROM detected_events WHERE status = :status")
    fun countByStatus(status: EventStatus): Flow<Int>

    @Query("SELECT * FROM detected_events WHERE id = :id")
    suspend fun getById(id: Long): DetectedEvent?

    /** 그룹 누적 병합 후보: 같은 채널·시작·모델원제목(baseTitle)이고 무시되지 않은 최근 건.
     *  방(room) 일치 여부는 호출측(Repository)이 추가 판정. start가 null이면 null끼리만 매칭. */
    @Query(
        "SELECT * FROM detected_events WHERE channel = :channel AND status != 'DISMISSED' " +
            "AND baseTitle = :baseTitle AND baseTitle != '' " +
            "AND ((:start IS NULL AND start IS NULL) OR start = :start) " +
            "AND createdAt >= :sinceMs ORDER BY createdAt DESC LIMIT 1",
    )
    suspend fun findMergeable(channel: String, baseTitle: String, start: String?, sinceMs: Long): DetectedEvent?

    /** 방-인지 병합 후보: 같은 채널·방·시작이고 무시되지 않은 최근 건(제목 흔들려도 그룹 누적은 한 일정).
     *  방이 있을 때만 사용 — 모델 제목(baseTitle)이 메시지마다 흔들리는 0.5B 한계를 우회. */
    @Query(
        "SELECT * FROM detected_events WHERE channel = :channel AND status != 'DISMISSED' " +
            "AND room = :room AND room != '' " +
            "AND ((:start IS NULL AND start IS NULL) OR start = :start) " +
            "AND createdAt >= :sinceMs ORDER BY createdAt DESC LIMIT 1",
    )
    suspend fun findMergeableByRoom(channel: String, room: String, start: String?, sinceMs: Long): DetectedEvent?

    @Update
    suspend fun update(event: DetectedEvent)

    @Query("UPDATE detected_events SET status = :status, calendarEventId = :calId, registeredAt = :registeredAt WHERE id = :id")
    suspend fun setStatus(id: Long, status: EventStatus, calId: Long?, registeredAt: Long?)

    /** 대시보드 '예비': 미등록(PENDING) + 일정이 오늘 이후(또는 날짜 미상). start ISO의 날짜부 비교. */
    @Query(
        "SELECT * FROM detected_events WHERE status = 'PENDING' " +
            "AND (start IS NULL OR substr(start, 1, 10) >= :today) ORDER BY start ASC",
    )
    fun observeActiveCandidates(today: String): Flow<List<DetectedEvent>>

    /** 대시보드 '등록': 오늘 등록된(registeredAt >= 오늘 0시) 것만. */
    @Query(
        "SELECT * FROM detected_events WHERE status IN ('ADDED', 'AUTO_ADDED') " +
            "AND registeredAt >= :sinceMs ORDER BY start ASC",
    )
    fun observeRegisteredSince(sinceMs: Long): Flow<List<DetectedEvent>>

    /** 예비 자동 정리: 일정 날짜가 오늘보다 지난 미등록 건 삭제. */
    @Query("DELETE FROM detected_events WHERE status = 'PENDING' AND start IS NOT NULL AND substr(start, 1, 10) < :today")
    suspend fun purgePastPending(today: String)

    @Delete
    suspend fun delete(event: DetectedEvent)

    @Query("DELETE FROM detected_events WHERE status = :status")
    suspend fun clearByStatus(status: EventStatus)

    /** 학습 페어 후보 중 아직 안 내보낸(신규) 것. status는 enum name으로 저장됨. */
    @Query("SELECT * FROM detected_events WHERE status IN ('ADDED', 'AUTO_ADDED', 'DISMISSED') AND exported = 0 ORDER BY createdAt ASC")
    suspend fun newTrainingCandidates(): List<DetectedEvent>

    /** 신규(미전송) 학습 후보 개수 — 내보내기 버튼 활성화 임계(10) 판단용. */
    @Query("SELECT COUNT(*) FROM detected_events WHERE status IN ('ADDED', 'AUTO_ADDED', 'DISMISSED') AND exported = 0")
    fun observeNewCandidateCount(): Flow<Int>

    /** 내보낸 신규 후보를 전송됨으로 표시(다음 신규 카운트에서 제외). */
    @Query("UPDATE detected_events SET exported = 1 WHERE status IN ('ADDED', 'AUTO_ADDED', 'DISMISSED') AND exported = 0")
    suspend fun markDecidedExported()
}
