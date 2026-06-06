package com.vibezent.calendaragent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.vibezent.calendaragent.databinding.ActivityOnboardingBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 첫 실행 설정 가이드: 모델 임포트 + 필요한 권한(알림·캘린더·문자·카톡 접근)을 체크리스트로 안내.
 * 각 항목은 완료 시 ✓로 표시되고 버튼이 사라진다. onResume마다 상태 갱신(권한 화면 복귀 반영).
 */
class OnboardingActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOnboardingBinding

    private val reqPerms = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { refresh() }

    private val pickModel = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { res -> if (res.resultCode == Activity.RESULT_OK) res.data?.data?.let { importModel(it) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOnboardingBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnModel.setOnClickListener {
            pickModel.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
            })
        }
        binding.btnNotif.setOnClickListener { reqPerms.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS)) }
        binding.btnCal.setOnClickListener {
            reqPerms.launch(arrayOf(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR))
        }
        binding.btnCalSelect.setOnClickListener { CalendarPicker.show(this) { refresh() } }
        binding.btnSms.setOnClickListener { reqPerms.launch(arrayOf(Manifest.permission.RECEIVE_SMS)) }
        binding.btnKakao.setOnClickListener { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        binding.startButton.setOnClickListener {
            SettingsStore.from(this).onboardingDone = true
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun granted(p: String) =
        ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED

    private fun listenerOn(): Boolean {
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        return flat.split(":").any { it.contains(packageName) }
    }

    private fun refresh() {
        step(binding.stepModelLabel, binding.btnModel, getString(R.string.step_model), ModelStore.exists(this))
        step(binding.stepNotifLabel, binding.btnNotif, getString(R.string.step_notif), granted(Manifest.permission.POST_NOTIFICATIONS))
        step(binding.stepCalLabel, binding.btnCal, getString(R.string.step_cal), granted(Manifest.permission.WRITE_CALENDAR))
        step(binding.stepCalSelectLabel, binding.btnCalSelect, getString(R.string.step_cal_select), SettingsStore.from(this).targetCalendarId != -1L)
        step(binding.stepSmsLabel, binding.btnSms, getString(R.string.step_sms), granted(Manifest.permission.RECEIVE_SMS))
        step(binding.stepKakaoLabel, binding.btnKakao, getString(R.string.step_kakao), listenerOn())
    }

    private fun step(label: TextView, btn: Button, title: String, done: Boolean) {
        label.text = if (done) "${getString(R.string.step_done)} $title" else title
        btn.visibility = if (done) View.GONE else View.VISIBLE
    }

    private fun importModel(uri: Uri) {
        Toast.makeText(this, R.string.importing_model, Toast.LENGTH_SHORT).show()
        lifecycleScope.launch {
            val ok = withContext(Dispatchers.IO) {
                try {
                    contentResolver.openInputStream(uri)?.use { input ->
                        ModelStore.modelFile(this@OnboardingActivity).outputStream().use { o -> input.copyTo(o) }
                    }
                    true
                } catch (e: Exception) {
                    false
                }
            }
            Toast.makeText(this@OnboardingActivity, if (ok) R.string.import_done else R.string.import_failed, Toast.LENGTH_SHORT).show()
            refresh()
        }
    }
}
