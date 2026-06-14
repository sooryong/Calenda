package com.calenda

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * 카카오톡 대화 화면을 '접근성'으로 읽어 양방향(내 송신 + 상대 수신) 말풍선을 캡처한다.
 *
 * 왜 필요한가:
 *   NotificationListener는 '수신' 알림만 본다 → 내가 보낸 확정("금요일 10시 …")이 안 잡혀
 *   협의→확정 멀티턴을 놓친다(박상로 케이스). 접근성은 화면에 렌더된 말풍선을 읽으므로
 *   내가 보낸 말풍선까지 보인다. 학습셋의 thread_context엔 이미 sender="나" 턴이 있고
 *   추출 타깃이 내 확정 발화인 케이스로 학습돼 있어 분포 안(in-distribution)이다.
 *
 * ★ 카톡 노드 구조 (uiautomator dump로 확인):
 *   - 말풍선 텍스트는 text가 아니라 **content-desc**에 있고, resource-id="…:id/message"
 *     노드에 담긴다(클래스는 Button 또는 TextView). 일부 링크/지도 말풍선만 text= 사용.
 *   - 방 제목: resource-id="…:id/toolbar_default_title_text" 의 content-desc.
 *   - 시각 라벨(오후 5:33)은 커스텀 드로잉이라 노드로 안 노출됨 → 컨텍스트 시각은 now()로 표기.
 *   resource-id로 타깃팅하므로 좌표 휴리스틱(시각/날짜/잡음 필터)이 불필요하고 견고하다.
 *
 * 발신자 귀속: 말풍선 중심 x가 화면 우측이면 내 것(sender="나"), 좌측이면 상대(방 제목으로 표기).
 * 트리거: 화면 '맨 아래' 말풍선이 바뀌면(새 송·수신) 그 말풍선을 추출 대상, 앞 말풍선들을 <대화내역>으로.
 */
class KakaoAccessibilityService : AccessibilityService() {

    private val main = Handler(Looper.getMainLooper())
    private val pending = Runnable { scrapeActiveWindow() }

    /** 방(room)별 '이미 처리한' 말풍선 서명 집합(내용 기반, 캡처 시각 무관).
     *  스크롤로 같은 메시지가 다시 바닥에 와도 재처리(중복 이벤트)하지 않도록. */
    private val seenByRoom = HashMap<String, LinkedHashSet<String>>()

    override fun onServiceConnected() {
        super.onServiceConnected()
        isActive = true
        Log.d(TAG, "accessibility connected — kakao 양방향 캡처 활성")
    }

    override fun onDestroy() {
        isActive = false
        super.onDestroy()
    }

    override fun onInterrupt() {}

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null || event.packageName != KAKAO_PKG) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> debounceScrape()
        }
    }

    /** 콘텐츠 변경 이벤트가 몰리므로 ~400ms 디바운스 후 1회만 스크랩. */
    private fun debounceScrape() {
        main.removeCallbacks(pending)
        main.postDelayed(pending, DEBOUNCE_MS)
    }

    private fun scrapeActiveWindow() {
        val screenW = resources.displayMetrics.widthPixels

        // 카톡 채팅 내용이 'active window'가 아닐 수 있어(오버레이/IME 등) windows 전체를 순회한다.
        // id/message·제목 id는 카톡 전용이라 다른 앱 창을 같이 훑어도 안전.
        val roots = ArrayList<AccessibilityNodeInfo>()
        val ws = windows
        if (!ws.isNullOrEmpty()) ws.forEach { w -> w.root?.let { roots.add(it) } }
        else rootInActiveWindow?.let { roots.add(it) }
        if (roots.isEmpty()) { Log.d(TAG, "scrape: no window roots"); return }

        // id/message(말풍선)와 id/toolbar_default_title_text(방 제목)만 수집.
        val msgs = ArrayList<MsgNode>()
        var room = ""
        for (r in roots) collect(r, msgs) { title -> if (room.isEmpty()) room = title }
        Log.d(TAG, "scrape: roots=${roots.size} room=\"$room\" msgs=${msgs.size}")  // 진단
        if (room.isEmpty() || msgs.isEmpty()) return   // 채팅 목록 화면 등 → 무시

        val ordered = msgs.sortedBy { it.bounds.top }.map { n ->
            val mine = (n.bounds.left + n.bounds.right) / 2 > screenW / 2
            Bubble(fromMe = mine, text = n.text)
        }

        // 바닥 말풍선(=가장 최근 메시지)을 트리거하되, 내용 기반으로 '이미 처리'면 건너뛴다.
        // 스크롤로 옛 메시지가 다시 바닥에 와도 재트리거 안 함 → 중복 이벤트 방지(receivedAt 변동 무관).
        val bottom = ordered.last()
        val sig = "${bottom.fromMe}|${bottom.text}"
        val seen = seenByRoom.getOrPut(room) { LinkedHashSet() }
        if (!seen.add(sig)) return                     // 이미 처리한 메시지
        if (seen.size > SEEN_MAX) {                     // 오래된 서명부터 정리(상한)
            val it = seen.iterator()
            while (seen.size > SEEN_MAX && it.hasNext()) { it.next(); it.remove() }
        }

        // 트리거 = 바닥 말풍선, 컨텍스트 = 그 앞 말풍선들(최근 CONTEXT_MAX개). 줄바꿈은 한 줄로.
        // ★ 카톡은 말풍선별 실제 시각을 노드로 안 준다. 모든 턴에 now()를 찍으면 동일 시각이
        //   반복돼 모델이 그 숫자를 '약속 시각'으로 오인한다(예: 10:48 → minute 48). 그래서
        //   컨텍스트 턴은 트리거 시각에서 1분씩 과거로 흩뿌려(서로 다른 현실적 과거 시각) 오염을 줄인다.
        //   진짜 약속 시각은 메시지 '본문'(예: "10시")에서 모델이 추출한다.
        val now = System.currentTimeMillis()
        val ctxBubbles = ordered.dropLast(1).takeLast(CONTEXT_MAX)
        val context = ctxBubbles.mapIndexed { i, b ->
            val t = now - (ctxBubbles.size - i) * 60_000L
            ThreadTurn(
                time = ScheduleExtractor.clockOf(t),
                sender = if (b.fromMe) ME else room,
                message = b.text.replace(Regex("\\s+"), " ").trim(),
            )
        }

        val msg = IncomingMessage(
            channel = "kakao",
            sender = if (bottom.fromMe) ME else room,
            body = bottom.text,
            timeMillis = now,                          // 바닥=방금 도착/전송 → 실시간이 정확
            room = room,
            fromMe = bottom.fromMe,
            counterpart = room,
        )
        Log.d(TAG, "scraped room=$room fromMe=${bottom.fromMe} n=${ordered.size} body=\"${bottom.text.take(40)}\" ctx=${context.size}")
        MessagePipeline.onScraped(applicationContext, msg, context)
    }

    /** id/message·방제목 노드만 재귀 수집. 말풍선 텍스트는 content-desc 우선(없으면 text). */
    private fun collect(node: AccessibilityNodeInfo?, out: ArrayList<MsgNode>, onTitle: (String) -> Unit) {
        if (node == null) return
        when (node.viewIdResourceName) {
            MSG_ID -> {
                val t = (node.contentDescription ?: node.text)?.toString()?.trim()
                if (!t.isNullOrEmpty()) {
                    val r = Rect(); node.getBoundsInScreen(r)
                    if (r.width() > 0 && r.height() > 0) out.add(MsgNode(t, r))
                }
            }
            TITLE_ID -> {
                val t = (node.contentDescription ?: node.text)?.toString()?.trim()
                if (!t.isNullOrEmpty()) onTitle(t)
            }
        }
        for (i in 0 until node.childCount) collect(node.getChild(i), out, onTitle)
    }

    private data class MsgNode(val text: String, val bounds: Rect)
    private data class Bubble(val fromMe: Boolean, val text: String)

    companion object {
        private const val TAG = "KakaoA11y"
        private const val KAKAO_PKG = "com.kakao.talk"
        private const val MSG_ID = "com.kakao.talk:id/message"
        private const val TITLE_ID = "com.kakao.talk:id/toolbar_default_title_text"
        private const val DEBOUNCE_MS = 400L
        private const val CONTEXT_MAX = 5
        private const val SEEN_MAX = 300               // 방별 처리이력 상한(스크롤 재처리 방지용)
        private const val ME = "나"

        /** NotificationListener가 카톡 이중처리를 피하려고 참조하는 런타임 플래그. */
        @Volatile
        var isActive = false
            private set
    }
}
