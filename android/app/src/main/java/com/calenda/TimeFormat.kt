package com.calenda

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 메시지 수신시각 → 'M/d HH:mm'. receivedAt(ISO) 우선, 없으면 createdAt(저장 epoch). 카드·상세 공용. */
fun formatReceived(receivedIso: String, createdAt: Long): String {
    val out = SimpleDateFormat("M/d HH:mm", Locale.KOREA)
    if (receivedIso.isNotBlank()) {
        for (p in listOf("yyyy-MM-dd'T'HH:mm:ssXXX", "yyyy-MM-dd'T'HH:mmXXX", "yyyy-MM-dd'T'HH:mm:ss")) {
            try {
                return out.format(SimpleDateFormat(p, Locale.KOREA).parse(receivedIso) ?: continue)
            } catch (_: Exception) { /* try next */ }
        }
    }
    return out.format(Date(createdAt))
}
