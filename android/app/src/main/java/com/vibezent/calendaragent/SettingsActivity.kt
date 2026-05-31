package com.vibezent.calendaragent

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.SeekBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.common.api.ApiException
import com.vibezent.calendaragent.databinding.ActivitySettingsBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 설정: 자동 등록 토글·신뢰도 임계값·채널 토글 + 학습 데이터 내보내기(경로 1).
 * 모든 값은 SettingsStore(SharedPreferences)에 즉시 저장 — 파이프라인/라우터가 공유.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private val settings by lazy { SettingsStore.from(this) }

    private val gmailSignIn = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { res ->
        if (res.resultCode == Activity.RESULT_OK) {
            try {
                GoogleSignIn.getSignedInAccountFromIntent(res.data).getResult(ApiException::class.java)
                GmailPollWorker.schedule(this)
                Toast.makeText(this, getString(R.string.gmail_connected, GmailAuth.email(this) ?: ""), Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this, R.string.gmail_failed, Toast.LENGTH_LONG).show()
            }
        }
        refreshGmail()
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

        // 채널 토글
        binding.chKakao.isChecked = settings.channelEnabled("kakao")
        binding.chSms.isChecked = settings.channelEnabled("sms")
        binding.chGmail.isChecked = settings.channelEnabled("gmail")
        binding.chKakao.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("kakao", v) }
        binding.chSms.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("sms", v) }
        binding.chGmail.setOnCheckedChangeListener { _, v -> settings.setChannelEnabled("gmail", v) }

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

        // Gmail 연결/해제
        binding.gmailButton.setOnClickListener {
            if (GmailAuth.isConnected(this)) {
                GmailAuth.client(this).signOut()
                GmailPollWorker.cancel(this)
                refreshGmail()
            } else {
                gmailSignIn.launch(GmailAuth.client(this).signInIntent)
            }
        }
        refreshGmail()

        // 학습 데이터 내보내기
        binding.exportButton.setOnClickListener { exportFeedback() }

        // 디버그(수동 추출)
        binding.debugButton.setOnClickListener { startActivity(Intent(this, DebugActivity::class.java)) }
    }

    override fun onResume() {
        super.onResume()
        refreshGmail()
    }

    private fun refreshGmail() {
        val connected = GmailAuth.isConnected(this)
        binding.gmailStatus.text =
            if (connected) getString(R.string.gmail_connected, GmailAuth.email(this) ?: "")
            else getString(R.string.gmail_not_connected)
        binding.gmailButton.setText(if (connected) R.string.gmail_disconnect else R.string.gmail_connect)
    }

    private fun exportFeedback() {
        binding.exportButton.isEnabled = false
        binding.exportResult.text = getString(R.string.export_running)
        lifecycleScope.launch {
            val res = withContext(Dispatchers.IO) { FeedbackExporter.export(this@SettingsActivity) }
            binding.exportResult.text = getString(R.string.export_result, res.pairs, res.skipped, res.file.absolutePath)
            binding.exportButton.isEnabled = true
        }
    }
}
