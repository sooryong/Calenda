package com.vibezent.calendaragent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * 수신 SMS를 가로채 파이프라인에 넣는다. (RECEIVE_SMS 권한 필요, Manifest 등록 + 런타임 허용)
 * 멀티파트(분할) 문자는 발신번호 기준으로 본문을 이어붙인다.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (parts.isEmpty()) return

        val address = parts[0].originatingAddress ?: "unknown"
        val body = parts.joinToString("") { it.messageBody ?: "" }
        val time = parts[0].timestampMillis.takeIf { it > 0 } ?: System.currentTimeMillis()

        MessagePipeline.onMessage(
            context.applicationContext,
            IncomingMessage(channel = "sms", sender = address, body = body, timeMillis = time),
        )
    }
}
