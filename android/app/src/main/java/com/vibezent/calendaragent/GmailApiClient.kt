package com.vibezent.calendaragent

import android.content.Context
import android.util.Base64
import android.util.Log
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Tasks
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Gmail 풀바디 연동 — 알림 미리보기는 본문 앞부분만 줘서 묻힌 일정(예: 3문단째 "6/16 출범식")을 놓친다.
 * 그래서 opt-in으로 OAuth gmail.readonly 인가를 받아 **본문 전체**를 REST로 가져와 같은 파이프라인에 넣는다.
 *
 * 설계 원칙:
 *  - 무거운 google-api-services-gmail 대신 AuthorizationClient(액세스 토큰) + OkHttp(REST) + org.json만 쓴다.
 *  - 인가(UI 동의)는 Activity가, 백그라운드 증분 동기화는 GmailSyncWorker가 호출(silentToken).
 *  - 가져온 메일은 MessagePipeline.onMessage(channel="gmail")로 흘려보낸다 → 휴리스틱·모델·dedupeKey 그대로 재사용.
 *    (알림 캡처와 풀바디가 같은 메일을 둘 다 봐도 dedupeKey가 중복 등록을 막는다.)
 *
 * ★ 동작 전제(사용자 1회 설정): Google Cloud에 OAuth 클라이언트(Android, package=com.calendaragent + SHA-1) +
 *   동의화면에 gmail.readonly 추가 + 테스트 사용자 등록. 자세히는 android/GMAIL_API.md.
 */
object GmailApiClient {
    private const val TAG = "GmailApiClient"
    const val SCOPE_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
    private const val BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

    private val http = OkHttpClient.Builder()
        .callTimeout(30, TimeUnit.SECONDS)
        .build()

    /** 인가 요청 객체(Activity가 Identity.getAuthorizationClient(this).authorize(req)로 사용). */
    fun authRequest(): AuthorizationRequest =
        AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(SCOPE_GMAIL_READONLY)))
            .build()

    /**
     * 백그라운드용 무-UI 토큰. 사용자가 이미 동의했으면 액세스 토큰을 반환, 재동의가 필요하면 null.
     * Worker(코루틴)에서 호출. Tasks.await는 블로킹이라 IO 디스패처에서.
     */
    suspend fun silentToken(ctx: Context): String? = withContext(Dispatchers.IO) {
        try {
            val result = Tasks.await(
                Identity.getAuthorizationClient(ctx.applicationContext).authorize(authRequest())
            )
            if (result.hasResolution()) {
                // UI 동의가 필요(최초/만료) → 백그라운드에선 처리 불가. Activity에서 인가 후 재시도.
                Log.d(TAG, "silentToken: needs user consent (hasResolution)")
                null
            } else {
                result.accessToken
            }
        } catch (e: Exception) {
            Log.w(TAG, "silentToken failed: ${e.message}")
            null
        }
    }

    /**
     * 마지막 동기화 이후 새 메일을 가져와 파이프라인에 주입. 반환=주입한 메일 수.
     * 증분 기준: SettingsStore.gmailLastSyncMillis(internalDate ms). 처음엔 최근 3일만.
     */
    suspend fun sync(appCtx: Context, accessToken: String): Int = withContext(Dispatchers.IO) {
        val settings = SettingsStore.from(appCtx)
        val since = settings.gmailLastSyncMillis
        val ids = listMessageIds(accessToken) ?: return@withContext 0
        var maxSeen = since
        var ingested = 0
        for (id in ids) {
            val msg = getMessage(accessToken, id) ?: continue
            if (msg.internalDate <= since) continue          // 증분: 이미 본 것 건너뜀
            if (msg.body.isBlank()) continue
            // 같은 파이프라인으로: 휴리스틱 → 모델 → resolver → dedupeKey 저장
            MessagePipeline.onMessage(
                appCtx,
                IncomingMessage(
                    channel = "gmail",
                    sender = msg.from,
                    body = msg.body,
                    timeMillis = msg.internalDate,
                    room = "",
                ),
            )
            ingested++
            if (msg.internalDate > maxSeen) maxSeen = msg.internalDate
        }
        if (maxSeen > since) settings.gmailLastSyncMillis = maxSeen
        Log.d(TAG, "sync: ingested=$ingested (since=$since → $maxSeen)")
        ingested
    }

    // ── Gmail REST ────────────────────────────────────────────────────────────

    /** 최근 메일 id 목록. 처음(since=0)이면 newer_than:3d, 이후는 1d면 폴링 주기상 충분(증분은 코드에서 한 번 더). */
    private fun listMessageIds(token: String): List<String>? {
        val url = "$BASE/messages?maxResults=25&q=" +
            java.net.URLEncoder.encode("in:inbox newer_than:3d", "UTF-8")
        val json = get(url, token) ?: return null
        val arr = json.optJSONArray("messages") ?: return emptyList()
        return (0 until arr.length()).map { arr.getJSONObject(it).getString("id") }
    }

    private data class Mail(val from: String, val subject: String, val body: String, val internalDate: Long)

    private fun getMessage(token: String, id: String): Mail? {
        val json = get("$BASE/messages/$id?format=full", token) ?: return null
        val payload = json.optJSONObject("payload") ?: return null
        val headers = payload.optJSONArray("headers")
        var from = ""; var subject = ""
        if (headers != null) {
            for (i in 0 until headers.length()) {
                val h = headers.getJSONObject(i)
                when (h.optString("name").lowercase()) {
                    "from" -> from = cleanFrom(h.optString("value"))
                    "subject" -> subject = h.optString("value")
                }
            }
        }
        val text = extractText(payload)
        val internalDate = json.optString("internalDate").toLongOrNull() ?: 0L
        // 본문 = 제목 + 본문(알림 캡처와 달리 풀바디). 제목에 일정요지가 있는 메일도 많아 함께 넣는다.
        val body = (if (subject.isNotBlank()) "$subject\n" else "") + text
        return Mail(from, subject, body.trim(), internalDate)
    }

    /** payload 트리에서 text/plain 우선 추출, 없으면 text/html 태그 제거. base64url 디코드. */
    private fun extractText(part: JSONObject): String {
        val mime = part.optString("mimeType")
        val bodyData = part.optJSONObject("body")?.optString("data").orEmpty()
        if (mime == "text/plain" && bodyData.isNotEmpty()) return decode(bodyData)
        val parts = part.optJSONArray("parts")
        if (parts != null) {
            // 1순위 text/plain
            for (i in 0 until parts.length()) {
                val t = extractText(parts.getJSONObject(i))
                if (t.isNotBlank()) return t
            }
        }
        if (mime == "text/html" && bodyData.isNotEmpty()) return stripHtml(decode(bodyData))
        return ""
    }

    private fun decode(b64url: String): String = try {
        String(Base64.decode(b64url, Base64.URL_SAFE or Base64.NO_WRAP), Charsets.UTF_8)
    } catch (e: Exception) { "" }

    private fun stripHtml(html: String): String =
        html.replace(Regex("(?s)<(script|style).*?</\\1>"), " ")
            .replace(Regex("<[^>]+>"), " ")
            .replace(Regex("&nbsp;|&amp;|&lt;|&gt;|&#\\d+;"), " ")
            .replace(Regex("[ \\t]+"), " ")
            .replace(Regex("\\n{3,}"), "\n\n")
            .trim()

    /** "홍길동 <a@b.com>" → "홍길동", 이름 없으면 주소 그대로. */
    private fun cleanFrom(raw: String): String {
        val name = raw.substringBefore('<').trim().trim('"')
        return name.ifBlank { raw.substringAfter('<').substringBefore('>').trim().ifBlank { raw.trim() } }
    }

    private fun get(url: String, token: String): JSONObject? {
        val req = Request.Builder().url(url).header("Authorization", "Bearer $token").get().build()
        return try {
            http.newCall(req).execute().use { resp ->
                val b = resp.body?.string()
                if (!resp.isSuccessful) { Log.w(TAG, "GET $url → ${resp.code}: ${b?.take(200)}"); return null }
                b?.let { JSONObject(it) }
            }
        } catch (e: Exception) {
            Log.w(TAG, "GET $url failed: ${e.message}"); null
        }
    }
}
