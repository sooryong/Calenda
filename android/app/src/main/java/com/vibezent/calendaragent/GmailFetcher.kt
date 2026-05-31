package com.vibezent.calendaragent

import android.content.Context
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Gmail REST API로 최근 메일을 읽어 파이프라인(channel="gmail")에 주입.
 * 클라이언트 라이브러리 대신 HttpURLConnection + Bearer 토큰으로 경량 호출.
 * 이미 처리한 메시지 id는 prefs에 저장해 중복 추론을 막는다.
 */
object GmailFetcher {
    private const val TAG = "GmailFetcher"
    private const val BASE = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    /** 최근 메일 폴링 → 새 메일만 파이프라인에 주입. 주입한 건수 반환. */
    fun poll(appCtx: Context): Int {
        if (!SettingsStore.from(appCtx).channelEnabled("gmail")) return 0
        val acct = GmailAuth.account(appCtx)?.account ?: return 0
        val token = GmailAuth.accessToken(appCtx, acct) ?: return 0

        val ids = listRecent(token)
        if (ids.isEmpty()) return 0

        val prefs = appCtx.getSharedPreferences("gmail_seen", Context.MODE_PRIVATE)
        val seen = prefs.getStringSet("ids", emptySet()) ?: emptySet()
        val newSeen = HashSet(seen)
        var fed = 0
        for (id in ids) {
            if (seen.contains(id)) continue
            val msg = getMessage(token, id)
            newSeen.add(id)
            if (msg != null) {
                MessagePipeline.onMessage(appCtx, msg)
                fed++
            }
        }
        // seen 집합 상한 (오래된 것 자연 탈락)
        prefs.edit().putStringSet("ids", newSeen.toList().takeLast(500).toHashSet()).apply()
        return fed
    }

    private fun listRecent(token: String): List<String> {
        val body = httpGet("$BASE?q=newer_than:2d&maxResults=15", token) ?: return emptyList()
        return try {
            val arr = JSONObject(body).optJSONArray("messages") ?: return emptyList()
            (0 until arr.length()).map { arr.getJSONObject(it).getString("id") }
        } catch (e: Exception) {
            Log.w(TAG, "list parse: ${e.message}"); emptyList()
        }
    }

    private fun getMessage(token: String, id: String): IncomingMessage? {
        val body = httpGet("$BASE/$id?format=metadata&metadataHeaders=From&metadataHeaders=Subject", token)
            ?: return null
        return try {
            val obj = JSONObject(body)
            val snippet = obj.optString("snippet", "")
            val internalDate = obj.optString("internalDate", "0").toLongOrNull() ?: System.currentTimeMillis()
            var from = ""
            var subject = ""
            obj.optJSONObject("payload")?.optJSONArray("headers")?.let { hs ->
                for (i in 0 until hs.length()) {
                    val h = hs.getJSONObject(i)
                    when (h.optString("name").lowercase()) {
                        "from" -> from = h.optString("value")
                        "subject" -> subject = h.optString("value")
                    }
                }
            }
            val sender = displayName(from)
            val text = listOf(subject, snippet).filter { it.isNotBlank() }.joinToString("\n")
            if (text.isBlank()) return null
            IncomingMessage(channel = "gmail", sender = sender, body = text, timeMillis = internalDate)
        } catch (e: Exception) {
            Log.w(TAG, "get parse: ${e.message}"); null
        }
    }

    /** "홍길동 <a@b.com>" → "홍길동", "a@b.com" → "a@b.com". */
    private fun displayName(from: String): String {
        val lt = from.indexOf('<')
        val name = if (lt > 0) from.substring(0, lt).trim().trim('"') else from.trim()
        return name.ifBlank { from.trim() }
    }

    private fun httpGet(urlStr: String, token: String): String? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                setRequestProperty("Authorization", "Bearer $token")
                connectTimeout = 15000
                readTimeout = 15000
            }
            if (conn.responseCode != 200) {
                Log.w(TAG, "HTTP ${conn.responseCode} for $urlStr")
                null
            } else {
                conn.inputStream.bufferedReader().use { it.readText() }
            }
        } catch (e: Exception) {
            Log.w(TAG, "httpGet: ${e.message}"); null
        } finally {
            conn?.disconnect()
        }
    }
}
