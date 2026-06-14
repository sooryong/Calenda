package com.calenda

import android.content.Context

/**
 * 개인화 별칭맵 (incremental learning 경로 2 — 온디바이스, 가중치 학습 없이 프라이버시 안전).
 * 사용자가 편집에서 잘못 추출된 location(예: 사람 이름 "정원구")을 지우면, 그 발신자에 대해
 * "그 토큰은 장소가 아님"을 기억한다. 이후 같은 발신자의 메시지에서 같은 토큰이 location으로
 * 추출되면 자동으로 제거 — DateResolver의 휴리스틱 가드가 못 잡는 케이스를 사용자 지식으로 보완.
 */
class AliasStore(ctx: Context) {
    private val prefs = ctx.applicationContext.getSharedPreferences("aliases", Context.MODE_PRIVATE)

    private fun key(sender: String) = "np:${sender.trim()}"

    /** 해당 발신자에게 '이 토큰은 장소가 아니다(사람 등)'를 기록. */
    fun markNotPlace(sender: String, token: String) {
        val t = token.trim()
        if (t.isEmpty()) return
        val cur = prefs.getStringSet(key(sender), emptySet()) ?: emptySet()
        prefs.edit().putStringSet(key(sender), HashSet(cur).apply { add(t) }).apply()
    }

    fun isNotPlace(sender: String, token: String): Boolean =
        prefs.getStringSet(key(sender), emptySet())?.contains(token.trim()) == true

    /** 학습된 별칭으로 보정: location이 그 발신자에서 '장소 아님'으로 표시됐으면 제거. */
    fun correctLocation(sender: String, ev: CalendarEvent): CalendarEvent {
        val loc = ev.location ?: return ev
        return if (isNotPlace(sender, loc)) ev.copy(location = null) else ev
    }

    companion object {
        fun from(ctx: Context) = AliasStore(ctx)
    }
}
