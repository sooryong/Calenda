package com.calenda

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch

/**
 * 수신 메시지 처리 파이프라인 (카톡 리스너 / SMS 리시버 공통 진입점).
 *
 *   적재 → 사전필터 → (모델 로드 보장) → 입력 조립(단일/멀티턴) → 추론 → 결과 분기
 *
 * 추론은 단일 스레드로 직렬화한다(온디바이스 LLM은 동시에 하나만; LlamaBridge도 @Synchronized).
 */
@OptIn(ExperimentalCoroutinesApi::class)
object MessagePipeline {
    private const val TAG = "MessagePipeline"
    private const val N_PREDICT = 256

    // 추론 전용 단일 워커 (메시지가 몰려도 한 번에 하나씩 처리)
    private val worker = CoroutineScope(
        SupervisorJob() + Dispatchers.Default.limitedParallelism(1)
    )

    /** 알림/SMS 리시버에서 호출(수신 메시지). 대화내역은 ConversationBuffer가 누적. */
    fun onMessage(appCtx: Context, msg: IncomingMessage) {
        Log.d(TAG, "onMessage ch=${msg.channel} sender=${msg.sender} body=\"${msg.body.take(40)}\"")
        if (msg.body.isBlank()) { Log.d(TAG, "skip: blank body"); return }
        if (!SettingsStore.from(appCtx).channelEnabled(msg.channel)) { Log.d(TAG, "skip: channel ${msg.channel} disabled"); return }
        val isNew = ConversationBuffer.add(msg)
        if (!isNew) { Log.d(TAG, "skip: duplicate (ConversationBuffer)"); return }
        if (!ScheduleHeuristics.looksScheduleRelated(msg.body)) { Log.d(TAG, "skip: heuristic pre-filter"); return }
        // Gmail은 멀티턴 불필요. 카톡/문자만 누적 대화내역 사용.
        val thread = if (msg.channel == "gmail") emptyList() else ConversationBuffer.contextBefore(msg.conversationKey)
        Log.d(TAG, "accepted → inference")
        worker.launch { runInference(appCtx, msg, thread) }
    }

    /**
     * 접근성 캡처에서 호출(카톡 양방향). 대화내역을 화면에서 직접 스크랩해 넘기므로
     * ConversationBuffer를 거치지 않는다(내 송신 말풍선도 트리거가 됨).
     */
    fun onScraped(appCtx: Context, msg: IncomingMessage, thread: List<ThreadTurn>) {
        if (msg.body.isBlank()) { Log.d(TAG, "skip(scraped): blank"); return }
        if (!SettingsStore.from(appCtx).channelEnabled(msg.channel)) { Log.d(TAG, "skip(scraped): channel disabled"); return }
        // 멀티턴 확정("네"/"좋아요")은 body에 일정 단서가 없고 컨텍스트에만 있다 →
        // body 또는 대화내역 중 하나라도 일정 단서가 있으면 추론(모델이 확정/유보를 판단).
        val hasCue = ScheduleHeuristics.looksScheduleRelated(msg.body) ||
            thread.any { ScheduleHeuristics.looksScheduleRelated(it.message) }
        if (!hasCue) { Log.d(TAG, "skip(scraped): heuristic"); return }
        Log.d(TAG, "accepted(scraped) → inference")
        worker.launch { runInference(appCtx, msg, thread) }
    }

    private suspend fun runInference(appCtx: Context, msg: IncomingMessage, thread: List<ThreadTurn>) {
        if (!ModelStore.ensureLoaded(appCtx)) {
            Log.d(TAG, "model not available — skip")
            return
        }
        val receivedAt = ScheduleExtractor.isoOf(msg.timeMillis)
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
            // 제목 출처(' · 발신자'): 내가 보낸 게 트리거면 "나"가 아니라 상대(counterpart)를 출처로.
            val titleSender = if (msg.fromMe) msg.counterpart.ifBlank { null } else msg.sender
            // 미해석 토큰 → 절대 시각 + 조합 제목 (앱이 계산), 그 뒤 개인 별칭맵으로 location 보정
            val event = AliasStore.from(appCtx).correctLocation(
                titleSender ?: msg.sender,
                DateResolver.resolveEvent(receivedAt, titleSender, ext.events.first()),
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
                baseTitle = ext.events.first().title.trim(),   // 모델 원제목(조합 전) — 그룹 누적 병합 키
                room = msg.room,
            )
            if (id != null) {
                EventRouter.route(appCtx, repo, id, event, msg)
            } else {
                Log.d(TAG, "duplicate event — skip")
            }
        }
    }
}
