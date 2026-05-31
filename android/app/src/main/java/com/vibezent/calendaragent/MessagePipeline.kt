package com.vibezent.calendaragent

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 수신 메시지 처리 파이프라인 (카톡 리스너 / SMS 리시버 공통 진입점).
 *
 *   적재 → 사전필터 → (모델 로드 보장) → 입력 조립(단일/멀티턴) → 추론 → 결과 분기
 *
 * 추론은 단일 스레드로 직렬화한다(온디바이스 LLM은 동시에 하나만; LlamaBridge도 @Synchronized).
 */
object MessagePipeline {
    private const val TAG = "MessagePipeline"
    private const val N_PREDICT = 256

    // 추론 전용 단일 워커 (메시지가 몰려도 한 번에 하나씩 처리)
    private val worker = CoroutineScope(
        SupervisorJob() + Dispatchers.Default.limitedParallelism(1)
    )

    /** 리시버/리스너에서 호출. applicationContext를 넘길 것. */
    fun onMessage(appCtx: Context, msg: IncomingMessage) {
        if (msg.body.isBlank()) return
        if (!SettingsStore.from(appCtx).channelEnabled(msg.channel)) return  // 채널 토글 OFF
        val isNew = ConversationBuffer.add(msg)
        if (!isNew) return                                   // 중복 알림 재게시 등
        if (!ScheduleHeuristics.looksScheduleRelated(msg.body)) return  // 배터리 절약 사전 필터
        worker.launch { runInference(appCtx, msg) }
    }

    private suspend fun runInference(appCtx: Context, msg: IncomingMessage) {
        if (!ModelStore.ensureLoaded(appCtx)) {
            Log.d(TAG, "model not available — skip")
            return
        }
        val receivedAt = ScheduleExtractor.isoOf(msg.timeMillis)
        val thread = ConversationBuffer.contextBefore(msg.conversationKey)
        val prompt = ScheduleExtractor.buildPrompt(
            channel = msg.channel,
            receivedAt = receivedAt,
            sender = msg.sender,
            message = msg.body,
            thread = thread,
        )
        val raw = LlamaBridge.complete(prompt, N_PREDICT)
        val ext = ScheduleExtractor.parse(raw)
        if (ext.parseError != null) {
            Log.w(TAG, "parse error: ${ext.parseError}")
            return
        }
        // has_schedule=false(아직 협의 중/일정 아님)면 아무것도 안 함
        if (ext.hasSchedule && ext.events.isNotEmpty()) {
            // 미해석 토큰 → 절대 시각 + 조합 제목 (앱이 계산), 그 뒤 개인 별칭맵으로 location 보정
            val event = AliasStore.from(appCtx).correctLocation(
                msg.sender,
                DateResolver.resolveEvent(receivedAt, msg.sender, ext.events.first()),
            )
            // 이벤트함에 영속화(상태=대기). 중복(dedupeKey)이면 null → 알림 생략.
            // receivedAt/modelRawJson/threadJson = incremental-learning 페어 재구성용 캡처.
            // 등록 정책(고신뢰도 자동 추가 / 저신뢰도 확인)은 EventRouter가 결정.
            val repo = EventRepository.from(appCtx)
            val id = repo.save(
                event, msg.channel, msg.sender, msg.body, EventStatus.PENDING,
                receivedAt = receivedAt,
                modelRawJson = ext.rawJson,
                threadJson = ScheduleExtractor.threadToJson(thread),
            )
            if (id != null) {
                EventRouter.route(appCtx, repo, id, event, msg)
            } else {
                Log.d(TAG, "duplicate event — skip")
            }
        }
    }
}
