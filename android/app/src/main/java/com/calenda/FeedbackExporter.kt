package com.calenda

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 누적된 사용자 피드백(추가/자동추가/무시/편집)을 학습 페어 JSONL로 내보낸다 (경로 1: incremental learning).
 * 출력은 scripts/_common 학습 페어와 동일 스키마:
 *   {scenario_id, received_at, channel, sender, language, thread_context?, message, gold, _feedback}
 * 사용자가 이 파일을 꺼내 Kaggle bf16 LoRA 루프(다음 라운드)에 합칠 수 있다.
 *
 * gold 결정:
 *   - editedJson 있으면     → 사용자 교정본이 정답              ★ 최우선(가장 깨끗)
 *   - 상태 DISMISSED         → {has_schedule:false}  (일정 아님/오탐; 되돌리기 포함)
 *   - 상태 ADDED/AUTO_ADDED  → modelRawJson (모델 추출이 맞았음 = 양성)
 *   - 그 외/직렬화 불가       → 스킵
 *
 * ⚠ 프라이버시: 원본 메시지(사적 내용)가 포함되므로 **사용자가 명시적으로 내보낼 때만** 생성한다.
 *   자동 업로드 없음. (음성 비율은 [[feedback_boost_negative_balance]]에 따라 라운드 큐레이션에서 조정.)
 */
object FeedbackExporter {

    data class Result(val file: File, val pairs: Int, val skipped: Int)

    suspend fun export(ctx: Context): Result {
        val repo = EventRepository.from(ctx)
        val rows = repo.newTrainingCandidates()   // 신규(미전송)만
        val sb = StringBuilder()
        var pairs = 0
        var skipped = 0
        for (r in rows) {
            val gold = goldFor(r)
            if (gold == null) {
                skipped++
                continue
            }
            val obj = JSONObject()
                .put("scenario_id", "feedback_${r.id}")
                .put("received_at", r.receivedAt)
                .put("channel", r.channel)
                .put("sender", r.sender)
                .put("language", "ko")
                .put("message", r.rawMessage)
                .put("gold", gold)
                // 출처 표시(라운드 큐레이션·필터용). EDITED는 date가 절대일자일 수 있어 상대화 검토 필요.
                .put("_feedback", if (r.editedJson != null) "EDITED" else r.status.name)
            r.threadJson?.let { obj.put("thread_context", JSONArray(it)) }
            sb.append(obj.toString()).append('\n')
            pairs++
        }
        val dir = File(ctx.getExternalFilesDir(null), "feedback").apply { mkdirs() }
        val file = File(dir, "feedback_export.jsonl")
        file.writeText(sb.toString())
        repo.markDecidedExported()   // 보낸 신규분을 전송됨 표시 → 신규 카운트 리셋
        return Result(file, pairs, skipped)
    }

    private fun goldFor(r: DetectedEvent): JSONObject? {
        r.editedJson?.let { return runCatching { JSONObject(it) }.getOrNull() }
        return when (r.status) {
            EventStatus.DISMISSED ->
                JSONObject().put("has_schedule", false).put("events", JSONArray())
            EventStatus.ADDED, EventStatus.AUTO_ADDED ->
                // 앱이 실제 등록한 형태(사람≠장소 가드 적용)로 정리해 내보냄.
                r.modelRawJson?.let { runCatching { sanitize(JSONObject(it)) }.getOrNull() }
            else -> null
        }
    }

    /**
     * 내보내는 gold를 앱의 등록 동작과 일치시킨다: 사람 이름이 location으로 오추출된 경우 제거
     * (DateResolver.dropPersonlikeLocation 미러). raw의 버그를 다음 라운드에 재학습시키지 않고,
     * 오히려 location 교정 신호를 루프에 흘려보낸다.
     */
    private fun sanitize(obj: JSONObject): JSONObject {
        val events = obj.optJSONArray("events") ?: return obj
        for (i in 0 until events.length()) {
            val e = events.optJSONObject(i) ?: continue
            val loc = e.optString("location", "").trim()
            if (loc.length < 2) continue
            val att = e.optJSONArray("attendees") ?: continue
            for (j in 0 until att.length()) {
                val name = att.optString(j, "").trim()
                if (name.isNotEmpty() && (name.contains(loc) || loc.contains(name))) {
                    e.put("location", JSONObject.NULL)
                    break
                }
            }
        }
        return obj
    }
}
