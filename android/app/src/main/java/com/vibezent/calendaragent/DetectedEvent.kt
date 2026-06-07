package com.vibezent.calendaragent

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import androidx.room.TypeConverter

/** 감지된 일정의 처리 상태. */
enum class EventStatus {
    PENDING,     // 감지됨, 사용자 확인 대기
    ADDED,       // 사용자가 확인 후 캘린더에 추가
    AUTO_ADDED,  // 고신뢰도라 자동 추가됨
    DISMISSED,   // 사용자가 무시
}

/**
 * 메시지에서 감지·해석된 일정 1건. 이벤트함(목록/편집/상태)의 영속 단위.
 * CalendarEvent(휘발성 표시용) + 출처/상태/중복키 메타를 합친 저장형.
 */
@Entity(
    tableName = "detected_events",
    indices = [Index(value = ["dedupeKey"], unique = true)],
)
data class DetectedEvent(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val title: String,
    val start: String?,        // ISO 8601 (+09:00) | YYYY-MM-DD(종일) | null
    val end: String?,
    val allDay: Boolean,
    val location: String?,
    val attendees: List<String>,
    val description: String?,
    val recurrence: String?,   // RRULE
    val confidence: Double,
    val channel: String,       // kakao | sms | gmail
    val sender: String,
    val rawMessage: String,    // 원본 메시지(검토·디버깅용)
    val room: String = "",        // 카톡 그룹 방이름(best-effort, EXTRA_CONVERSATION_TITLE). 그룹 누적 병합 보조키.
    val baseTitle: String = "",   // 모델 원(原)제목(조합 전). 같은 활동 병합 키(예: '동기회').
    val status: EventStatus,
    val dedupeKey: String,     // 중복 억제 키 (channel|start|title 정규화)
    val createdAt: Long,
    val calendarEventId: Long? = null,  // 자동/수동 등록 시 CalendarProvider event _id
    val registeredAt: Long? = null,     // 캘린더 등록된 시각(ms). 대시보드 '오늘 등록' 필터용
    val exported: Boolean = false,      // 학습 데이터로 이미 내보냈는지(신규 누적 카운트용)

    // ── incremental learning 캡처 (학습 페어 재구성용) ──────────────────
    val receivedAt: String = "",       // 원본 메시지 수신시각 ISO (학습 입력의 <수신시각>)
    val modelRawJson: String? = null,  // 모델 raw 추출 JSON (date 토큰·time 객체 — 토큰 스키마 그대로)
    val threadJson: String? = null,    // 멀티턴 <대화내역> 직렬화 (없으면 null=단일)
    val editedJson: String? = null,    // 사용자 교정본(Phase C 편집화면이 채움). 있으면 최우선 gold.
) {
    /** DB 저장형 → 캘린더 표시/등록용 휘발성 모델. */
    fun toCalendarEvent(): CalendarEvent = CalendarEvent(
        title = title, start = start, end = end, allDay = allDay,
        location = location, attendees = attendees, description = description,
        recurrence = recurrence, confidence = confidence,
    )
}

/** Room 타입 컨버터: List<String> ↔ String, EventStatus ↔ String. */
class Converters {
    // 참석자 구분자 U+0001 (사람 이름에 안 나오는 제어문자). 소스엔 raw 제어문자 대신 코드로.
    private val sep: String = 1.toChar().toString()

    @TypeConverter
    fun attendeesToStr(v: List<String>): String = v.joinToString(sep)

    @TypeConverter
    fun strToAttendees(s: String): List<String> =
        if (s.isEmpty()) emptyList() else s.split(sep)

    @TypeConverter
    fun statusToStr(s: EventStatus): String = s.name

    @TypeConverter
    fun strToStatus(s: String): EventStatus =
        runCatching { EventStatus.valueOf(s) }.getOrDefault(EventStatus.PENDING)
}
