package com.vibezent.calendaragent

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.SeekBar
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
import com.vibezent.calendaragent.databinding.ActivitySettingsBinding
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
    private val repo by lazy { EventRepository.from(this) }

    /** Gmail OAuth 동의 화면(PendingIntent) 결과 수신. */
    private val gmailAuthLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        try {
            val authResult = Identity.getAuthorizationClient(this)
                .getAuthorizationResultFromIntent(result.data)
            onGmailAuthorized(authResult.accessToken)
        } catch (e: Exception) {
            Toast.makeText(this, R.string.gmail_api_failed, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // 자동 등록
        binding.autoAddSwitch.isChecked = settings.autoAddEnabled
        binding.autoAddSwitch.setOnCheckedChangeListener { _, v -> settings.autoAddEnabled = v }

        // 임계값 (50~100% → 0.50~1.00)
        val pct = (settings.confidenceThreshold * 100).toInt().coerceIn(50, 100)
        binding.thresholdSeek.progress = pct
        binding.thresholdLabel.text = getString(R.string.threshold_label, pct)
        binding.thresholdSeek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, p: Int, fromUser: Boolean) {
                binding.thresholdLabel.text = getString(R.string.threshold_label, p)
            }
            override fun onStartTrackingTouch(sb: SeekBar) {}
            override fun onStopTrackingTouch(sb: SeekBar) {
                settings.confidenceThreshold = sb.progress / 100f
            }
        })

        // 엄격 등록(4W 필수)
        binding.strictRegisterSwitch.isChecked = settings.strictRegister
        binding.strictRegisterSwitch.setOnCheckedChangeListener { _, v -> settings.strictRegister = v }

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
        binding.batteryButton.setOnClickListener {
            try {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
                )
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

    /** 현재 저장 대상 캘린더를 버튼에 표시(미설정이면 자동선택 미리보기). */
    private fun refreshCalendarButton() {
        val cals = CalendarWriter.writableCalendars(this)
        val cur = cals.firstOrNull { it.id == settings.targetCalendarId }
            ?: cals.firstOrNull { it.isGoogleOwner }
        binding.calendarButton.text =
            if (cur != null) getString(R.string.calendar_current_fmt, "${cur.display} (${cur.account})")
            else getString(R.string.calendar_select)
    }

    private fun pickCalendar() = CalendarPicker.show(this) { refreshCalendarButton() }

    /** 버튼: 꺼져 있으면 OAuth 인가 시작, 켜져 있으면 연동 해제. */
    private fun toggleGmailApi() {
        if (settings.gmailApiEnabled) {
            settings.gmailApiEnabled = false
            GmailSyncWorker.disable(this)
            refreshGmailApiButton()
            Toast.makeText(this, R.string.gmail_api_off, Toast.LENGTH_SHORT).show()
            return
        }
        Identity.getAuthorizationClient(this).authorize(GmailApiClient.authRequest())
            .addOnSuccessListener { res ->
                val pi = res.pendingIntent
                if (res.hasResolution() && pi != null) {
                    gmailAuthLauncher.launch(IntentSenderRequest.Builder(pi.intentSender).build())
                } else {
                    onGmailAuthorized(res.accessToken)   // 이미 동의됨 → 토큰 즉시
                }
            }
            .addOnFailureListener {
                Toast.makeText(this, R.string.gmail_api_failed, Toast.LENGTH_SHORT).show()
            }
    }

    /** 인가 성공 → 풀바디 연동 on + 주기 폴링 등록 + 즉시 1회 동기화. */
    private fun onGmailAuthorized(token: String?) {
        settings.gmailApiEnabled = true
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
    }

    /** 설치된 gguf 버전(general.name)·업로드 시각 표시. 없으면 임포트 안내. */
    private fun refreshModelInfo() {
        val f = ModelStore.modelFile(this)
        binding.modelInfo.text = if (f.exists()) {
            val info = GgufInfo.read(f)
            val name = info.name ?: getString(R.string.model_version_unknown)
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
