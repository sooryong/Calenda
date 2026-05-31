package com.vibezent.calendaragent

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

    /** 학습 페어 후보: 사용자 판정이 끝난 행(추가/자동추가/무시). status는 enum name으로 저장됨. */
    @Query("SELECT * FROM detected_events WHERE status IN ('ADDED', 'AUTO_ADDED', 'DISMISSED') ORDER BY createdAt ASC")
    suspend fun trainingCandidates(): List<DetectedEvent>
}
