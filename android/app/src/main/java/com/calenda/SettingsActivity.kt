package com.calenda

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.gms.auth.api.identity.Identity
import com.calenda.databinding.ActivitySettingsBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 설정: 자동 등록 토글·신뢰도 임계값·채널 토글·백그라운드 상주 + 학습 데이터 보내기.
 * 학습 데이터: 신규(미전송) 누적이 임계(10) 이상일 때만 전송 가능. 동의 후 sooryong.byun@gmail.com으로 공유 전송.
 * Gmail은 별도 로그인 없이 알림 접근으로 수집.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private val settings by lazy { SettingsStore.from(this) }
    /** 인가 동의 진행 중 계정(런처 콜백이 이 계정으로 저장). 캘린더와 통합된 Google 계정. */
    private var pendingGmailAccount: String? = null
    private val repo by lazy { EventRepository.from(this) }

    /** Gmail OAuth 동의 화면(PendingIntent) 결과 수신. */
    private val gmailAuthLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        try {
            val authResult = Identity.getAuthorizationClient(this)
                .getAuthorizationResultFromIntent(result.data)
            val acct = pendingGmailAccount ?: selectedCalendarAccount() ?: ""
            onGmailAuthorized(acct, authResult.accessToken)
        } catch (e: Exception) {
            Log.w("Settings", "gmail consent failed", e)
            Toast.makeText(this, getString(R.string.gmail_api_failed) + ": " + (e.message ?: ""), Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // 일정 등록: 토글 없음. 자동등록 분기는 schedule_status="yes"가 결정(확정→자동, pending→예비, no→무시).

        // 채널 토글
        binding.chKakao.isChecked = settings.channelEnabled("kakao")
        binding.chSms.isChecked = settings.channelEnabled("sms")
        binding.chGmail.isChecked = settings.channelEnabled("gmail")
        binding.chKakao.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("kakao", v) }
        binding.chSms.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("sms", v) }
        binding.chGmail.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("gmail", v) }

        // Gmail 풀바디 연동(opt-in)
        binding.gmailApiButton.setOnClickListener { toggleGmailApi() }
        refreshGmailApiButton()

        // 백그라운드 상주 수집
        binding.collectorSwitch.isChecked = settings.collectorEnabled
        binding.collectorSwitch.setOnCheckedChangeListener { _, v ->
            settings.collectorEnabled = v
            if (v) CollectorService.start(this) else CollectorService.stop(this)
        }
        // 배터리 최적화 제외: 토글이 현재 제외 상태를 반영. 시스템만 변경 가능하므로 탭하면 해당 시스템 화면을 연다.
        binding.batterySwitch.isChecked = isBatteryExempt()
        binding.batterySwitch.setOnClickListener {
            binding.batterySwitch.isChecked = isBatteryExempt()   // 시각 상태를 실제값으로 고정(복귀 시 onResume이 재동기화)
            try {
                if (isBatteryExempt()) {
                    startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                } else {
                    startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
                }
            } catch (e: Exception) {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
        }

        // 학습 데이터 보내기 — 신규 10건 이상일 때만 활성화
        binding.exportButton.isEnabled = false
        binding.exportButton.setOnClickListener { confirmAndShare() }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                repo.newCandidateCount().collect { n -> updateExportButton(n) }
            }
        }

        // 저장할 캘린더 선택
        binding.calendarButton.setOnClickListener { pickCalendar() }

        // 디버그(수동 추출)
        binding.debugButton.setOnClickListener { startActivity(Intent(this, DebugActivity::class.java)) }

        refreshModelInfo()
        refreshCalendarButton()
    }

    /** 캘린더 계정(ID) 표시. 계정 1개면 선택 불필요(탭 비활성), 2개↑면 ▾ 표시 + 선택 가능. */
    private fun refreshCalendarButton() {
        val cals = CalendarWriter.writableCalendars(this)
        val accounts = cals.map { it.account }.distinct()
        val cur = cals.firstOrNull { it.id == settings.targetCalendarId }
            ?: cals.firstOrNull { it.isGoogleOwner }
            ?: cals.firstOrNull()
        val btn = binding.calendarButton
        when {
            cur == null -> {                              // 로그인된 Google 계정 없음
                btn.text = getString(R.string.calendar_id_none)
                btn.isClickable = false
            }
            accounts.size >= 2 -> {                       // 계정 2개↑ → 선택 가능(▾ 표시)
                btn.text = getString(R.string.calendar_id_pick_fmt, cur.account)
                btn.isClickable = true
            }
            else -> {                                     // 계정 1개 → 선택 불필요
                btn.text = getString(R.string.calendar_id_fmt, cur.account)
                btn.isClickable = false
            }
        }
    }

    private fun pickCalendar() = CalendarPicker.show(this) { refreshCalendarButton() }

    /** 선택한 캘린더가 속한 Google 계정명(캘린더·Gmail 통합 ID). 캘린더 미선택이면 null. */
    private fun selectedCalendarAccount(): String? =
        CalendarWriter.writableCalendars(this).firstOrNull { it.id == settings.targetCalendarId }?.account

    /** 버튼: 꺼져 있으면 **선택한 캘린더 계정**으로 Gmail 인가 시작(같은 ID 통합), 켜져 있으면 해제. */
    private fun toggleGmailApi() {
        if (settings.gmailApiEnabled) {
            settings.gmailApiEnabled = false
            settings.gmailAccount = null
            GmailSyncWorker.disable(this)
            refreshGmailApiButton()
            Toast.makeText(this, R.string.gmail_api_off, Toast.LENGTH_SHORT).show()
            return
        }
        // 캘린더·Gmail 통합: 위에서 고른 캘린더의 Google 계정으로 인가(별도 계정 선택 화면 없음).
        val account = selectedCalendarAccount()
        if (account == null) {
            Toast.makeText(this, R.string.gmail_need_calendar, Toast.LENGTH_LONG).show()
            return
        }
        pendingGmailAccount = account
        Identity.getAuthorizationClient(this).authorize(GmailApiClient.authRequest(account))
            .addOnSuccessListener { res ->
                val pi = res.pendingIntent
                if (res.hasResolution() && pi != null) {
                    gmailAuthLauncher.launch(IntentSenderRequest.Builder(pi.intentSender).build())
                } else {
                    onGmailAuthorized(account, res.accessToken)   // 이미 동의됨 → 토큰 즉시
                }
            }
            .addOnFailureListener { e ->
                Log.w("Settings", "gmail authorize failed", e)
                Toast.makeText(this, getString(R.string.gmail_api_failed) + ": " + (e.message ?: ""), Toast.LENGTH_LONG).show()
            }
    }

    /** 인가 성공 → 통합 계정 저장 + 풀바디 연동 on + 주기 폴링 등록 + 즉시 1회 동기화. */
    private fun onGmailAuthorized(account: String, token: String?) {
        settings.gmailApiEnabled = true
        settings.gmailAccount = account.ifBlank { selectedCalendarAccount() }
        settings.setChannelEnabled("gmail", true)
        GmailSyncWorker.enable(this)
        refreshGmailApiButton()
        Toast.makeText(this, R.string.gmail_api_ok, Toast.LENGTH_SHORT).show()
        token?.let { t ->
            lifecycleScope.launch(Dispatchers.IO) {
                try { GmailApiClient.sync(applicationContext, t) } catch (_: Exception) {}
            }
        }
    }

    private fun refreshGmailApiButton() {
        binding.gmailApiButton.setText(
            if (settings.gmailApiEnabled) R.string.gmail_api_connected else R.string.gmail_api_connect,
        )
    }

    override fun onResume() {
        super.onResume()
        refreshModelInfo()  // 디버그 화면에서 모델 임포트/교체 후 돌아오면 갱신
        binding.batterySwitch.isChecked = isBatteryExempt()  // 시스템 화면서 바꾸고 돌아오면 동기화
    }

    /** 이 앱이 배터리 최적화에서 제외돼 있는지(=백그라운드 상주 허용). 시스템만 변경 가능. */
    private fun isBatteryExempt(): Boolean =
        getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) == true

    /** 설치된 gguf 버전(general.name)·업로드 시각 표시. 없으면 임포트 안내. */
    private fun refreshModelInfo() {
        val f = ModelStore.modelFile(this)
        binding.modelInfo.text = if (f.exists()) {
            val info = GgufInfo.read(f)
            val name = info.shortName() ?: getString(R.string.model_version_unknown)
            val date = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.KOREA)
                .format(java.util.Date(info.lastModified))
            getString(R.string.model_version_fmt, name, date)
        } else {
            getString(R.string.model_missing)
        }
    }

    private fun updateExportButton(n: Int) {
        val ready = n >= EXPORT_THRESHOLD
        binding.exportButton.isEnabled = ready
        binding.exportButton.text =
            if (ready) getString(R.string.export_feedback, n)
            else getString(R.string.export_locked, n, EXPORT_THRESHOLD)
    }

    private fun confirmAndShare() {
        AlertDialog.Builder(this)
            .setTitle(R.string.export_confirm_title)
            .setMessage(R.string.export_confirm_msg)
            .setPositiveButton(R.string.export_confirm_ok) { _, _ -> exportAndShare() }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun exportAndShare() {
        binding.exportButton.isEnabled = false
        lifecycleScope.launch {
            val res = withContext(Dispatchers.IO) { FeedbackExporter.export(this@SettingsActivity) }
            try {
                val uri = FileProvider.getUriForFile(this@SettingsActivity, "$packageName.fileprovider", res.file)
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "application/json"
                    putExtra(Intent.EXTRA_EMAIL, arrayOf(COLLECT_EMAIL))
                    putExtra(Intent.EXTRA_SUBJECT, getString(R.string.export_mail_subject))
                    putExtra(Intent.EXTRA_TEXT, getString(R.string.export_mail_body, res.pairs))
                    putExtra(Intent.EXTRA_STREAM, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                startActivity(Intent.createChooser(send, getString(R.string.export_chooser)))
            } catch (e: Exception) {
                Toast.makeText(this@SettingsActivity, R.string.calendar_add_failed, Toast.LENGTH_SHORT).show()
            }
            // 카운트(Flow)가 0으로 갱신되며 버튼은 자동 비활성화됨.
        }
    }

    companion object {
        private const val EXPORT_THRESHOLD = 10
        private const val COLLECT_EMAIL = "sooryong.byun@gmail.com"
    }
}
