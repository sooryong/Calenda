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

    @Query("SELECT COUNT(*) FROM detected_events WHERE status = :status")
    fun countByStatus(status: EventStatus): Flow<Int>

    @Query("SELECT * FROM detected_events WHERE id = :id")
    suspend fun getById(id: Long): DetectedEvent?

    @Update
    suspend fun update(event: DetectedEvent)

    @Query("UPDATE detected_events SET status = :status, calendarEventId = :calId WHERE id = :id")
    suspend fun setStatus(id: Long, status: EventStatus, calId: Long?)

    @Delete
    suspend fun delete(event: DetectedEvent)

    @Query("DELETE FROM detected_events WHERE status = :status")
    suspend fun clearByStatus(status: EventStatus)

    /** 학습 페어 후보: 사용자 판정이 끝난 행(추가/자동추가/무시). status는 enum name으로 저장됨. */
    @Query("SELECT * FROM detected_events WHERE status IN ('ADDED', 'AUTO_ADDED', 'DISMISSED') ORDER BY createdAt ASC")
    suspend fun trainingCandidates(): List<DetectedEvent>
}
