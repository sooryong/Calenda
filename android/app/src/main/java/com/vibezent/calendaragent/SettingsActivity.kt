package com.vibezent.calendaragent

import android.os.Bundle
import android.widget.SeekBar
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
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

        // 학습 데이터 내보내기
        binding.exportButton.setOnClickListener { exportFeedback() }
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
