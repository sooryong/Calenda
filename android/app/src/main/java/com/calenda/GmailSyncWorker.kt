package com.calenda

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Gmail 풀바디 증분 동기화 워커. 주기적으로(기본 ~30분) 무-UI 토큰을 받아 새 메일을 가져와 파이프라인에 넣는다.
 * 동의 만료/철회 시 silentToken=null → 그냥 다음 주기에 재시도(사용자가 설정에서 재인가하면 복구).
 */
class GmailSyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        if (!SettingsStore.from(ctx).gmailApiEnabled) return Result.success()
        return try {
            val token = GmailApiClient.silentToken(ctx) ?: run {
                Log.d(TAG, "no silent token (needs re-consent) — skip this cycle")
                return Result.success()   // 재시도는 다음 주기. retry 폭주 방지.
            }
            GmailApiClient.sync(ctx, token)
            Result.success()
        } catch (e: Exception) {
            Log.w(TAG, "doWork failed: ${e.message}")
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "GmailSyncWorker"
        private const val WORK_NAME = "gmail_sync"

        /** 사용자가 Gmail 풀바디 연동을 켜면 호출 — 주기 폴링 등록(네트워크 연결 시에만). */
        fun enable(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<GmailSyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
                )
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
                WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, req
            )
        }

        fun disable(ctx: Context) {
            WorkManager.getInstance(ctx).cancelUniqueWork(WORK_NAME)
        }
    }
}
