package com.calenda

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 재부팅 후 자동 수집이 켜져 있었으면 상주 서비스를 복원. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED &&
            SettingsStore.from(context).collectorEnabled
        ) {
            // 일부 OS/제조사에서 부팅 시 FGS 시작이 제한될 수 있음 → 실패해도 크래시 방지.
            try {
                CollectorService.start(context.applicationContext)
            } catch (e: Exception) {
                // 무시: 사용자가 앱을 한 번 열면 서비스가 다시 뜬다.
            }
        }
    }
}
