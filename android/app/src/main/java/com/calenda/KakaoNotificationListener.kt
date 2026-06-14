package com.calenda

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * 알림 캡처 수집기 (카카오톡 + Gmail). 공식 메시지 API 없이 알림 텍스트를 관측한다.
 * (사용자가 '알림 접근 권한'을 허용해야 동작.) 클래스명은 호환 위해 유지 — 바꾸면 사용자가
 * 알림 접근을 재허용해야 함(권한이 컴포넌트명에 묶임).
 *
 * 한계:
 *  - '수신' 알림만 보임. 본문이 잘리거나 묶음 알림일 수 있음 → 요약(GROUP_SUMMARY) 스킵.
 *  - 카톡: title=방/상대 이름, body=메시지. Gmail: title=발신자, body=메일 제목(미리보기 있으면 첨부).
 */
class KakaoNotificationListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val channel = when (sbn.packageName) {
            KAKAO_PKG -> "kakao"
            GMAIL_PKG -> "gmail"
            else -> return
        }
        // 하이브리드: 접근성 서비스가 켜져 있으면 카톡은 그쪽이 양방향으로 소유 → 알림 경로는 양보(이중처리 방지).
        // 접근성이 꺼져 있으면(채팅방 닫힘 등) 종전대로 알림으로 수신만이라도 잡는다. Gmail은 항상 알림 경로.
        if (channel == "kakao" && KakaoAccessibilityService.isActive) return

        val n = sbn.notification ?: return
        // 묶음 요약 알림은 개별 메시지가 아님 → 스킵
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        // 그룹 대화 방이름(MessagingStyle): 그룹챗에서만 채워짐(1:1은 보통 비어 있음). 누적 병합 보조키.
        val room = if (channel == "kakao")
            extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString()?.trim().orEmpty()
        else ""
        // Gmail은 본문이 메일 제목 — 미리보기(BigText)가 있으면 더 풍부하게 사용.
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim().orEmpty()
        val body = if (channel == "gmail" && big.isNotEmpty()) big else text
        if (body.isEmpty() || title.isEmpty()) return

        val time = sbn.postTime.takeIf { it > 0 } ?: System.currentTimeMillis()
        MessagePipeline.onMessage(
            applicationContext,
            IncomingMessage(channel = channel, sender = title, body = body, timeMillis = time, room = room),
        )
    }

    companion object {
        private const val KAKAO_PKG = "com.kakao.talk"
        private const val GMAIL_PKG = "com.google.android.gm"
    }
}
