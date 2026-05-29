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
        val isNew = ConversationBuffer.add(msg)
        if (!isNew) return                                   // 중복 알림 재게시 등
        if (!ScheduleHeuristics.looksScheduleRelated(msg.body)) return  // 배터리 절약 사전 필터
        worker.launch { runInference(appCtx, msg) }
    }

    private fun runInference(appCtx: Context, msg: IncomingMessage) {
        if (!ModelStore.ensureLoaded(appCtx)) {
            Log.d(TAG, "model not available — skip")
            return
        }
        val thread = ConversationBuffer.contextBefore(msg.conversationKey)
        val prompt = ScheduleExtractor.buildPrompt(
            channel = msg.channel,
            receivedAt = ScheduleExtractor.isoOf(msg.timeMillis),
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
            ScheduleNotifier.notify(appCtx, ext.events.first(), msg)
        }
    }
}
