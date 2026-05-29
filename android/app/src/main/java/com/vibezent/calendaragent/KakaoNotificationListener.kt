package com.vibezent.calendaragent

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * 카카오톡은 공식 메시지 API가 없어, 알림 텍스트를 가로채는 방식으로 수신 메시지를 관측한다.
 * (사용자가 '알림 접근 권한'을 직접 허용해야 동작 — Settings에서 활성화.)
 *
 * 한계:
 *  - '수신' 알림만 보임 (내가 보낸 메시지는 안 들어옴).
 *  - 본문이 잘리거나 묶음(grouped) 알림일 수 있음 → 요약 알림은 스킵.
 *  - 그룹채팅이면 title=방 이름, 1:1이면 title=상대 이름.
 */
class KakaoNotificationListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName != KAKAO_PKG) return

        val n = sbn.notification ?: return
        // 묶음 요약 알림은 개별 메시지가 아님 → 스킵
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        if (text.isEmpty() || title.isEmpty()) return

        val time = sbn.postTime.takeIf { it > 0 } ?: System.currentTimeMillis()
        MessagePipeline.onMessage(
            applicationContext,
            IncomingMessage(channel = "kakao", sender = title, body = text, timeMillis = time),
        )
    }

    companion object {
        private const val KAKAO_PKG = "com.kakao.talk"
    }
}
