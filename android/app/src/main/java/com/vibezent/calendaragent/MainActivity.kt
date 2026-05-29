package com.vibezent.calendaragent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.vibezent.calendaragent.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var lastExtraction: Extraction? = null

    // 모델 파일 위치는 ModelStore로 중앙화 (백그라운드 수집과 동일 경로 공유)
    private val modelFile: File
        get() = ModelStore.modelFile(this)

    private val requestPerms = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { refreshCollectStatus() }

    private val pickModel = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { res ->
        if (res.resultCode == Activity.RESULT_OK) {
            res.data?.data?.let { importModel(it) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.receivedAtInput.setText(ScheduleExtractor.nowIso())
        binding.channelInput.setText("kakao")

        refreshModelStatus()

        binding.loadModelButton.setOnClickListener {
            if (modelFile.exists()) loadModel() else pickModelFile()
        }
        binding.reimportButton.setOnClickListener { pickModelFile() }
        binding.extractButton.setOnClickListener { runExtraction() }
        binding.addCalendarButton.setOnClickListener { addToCalendar() }

        // 자동 수집 권한
        binding.notifAccessButton.setOnClickListener {
            // 카톡 알림 가로채기: 사용자가 직접 '알림 접근'에서 본 앱을 켜야 함
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        binding.smsPermButton.setOnClickListener {
            requestPerms.launch(arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.POST_NOTIFICATIONS))
        }
    }

    override fun onResume() {
        super.onResume()
        // 알림 접근/권한 화면에서 돌아오면 상태 갱신
        refreshCollectStatus()
    }

    private fun isNotificationListenerEnabled(): Boolean {
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        return flat.split(":").any { it.contains(packageName) }
    }

    private fun isSmsGranted(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED

    private fun refreshCollectStatus() {
        val notif = if (isNotificationListenerEnabled()) getString(R.string.on) else getString(R.string.off)
        val sms = if (isSmsGranted()) getString(R.string.on) else getString(R.string.off)
        binding.collectStatus.text = getString(R.string.collect_status, notif, sms)
        binding.notifAccessButton.isEnabled = !isNotificationListenerEnabled()
        binding.smsPermButton.isEnabled = !isSmsGranted()
    }

    private fun refreshModelStatus() {
        when {
            LlamaBridge.loaded -> {
                binding.modelStatus.text = getString(R.string.model_loaded)
                binding.loadModelButton.text = getString(R.string.reload_model)
                binding.extractButton.isEnabled = true
            }
            modelFile.exists() -> {
                binding.modelStatus.text = getString(R.string.model_present_not_loaded)
                binding.loadModelButton.text = getString(R.string.load_model)
                binding.extractButton.isEnabled = false
            }
            else -> {
                binding.modelStatus.text = getString(R.string.model_missing)
                binding.loadModelButton.text = getString(R.string.import_model)
                binding.extractButton.isEnabled = false
            }
        }
        // 모델 파일이 이미 있으면 '모델 교체' 버튼 노출 (없으면 로드 버튼이 곧 임포트라 불필요)
        binding.reimportButton.visibility = if (modelFile.exists()) View.VISIBLE else View.GONE
    }

    private fun pickModelFile() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
        }
        pickModel.launch(intent)
    }

    private fun importModel(uri: Uri) {
        binding.modelStatus.text = getString(R.string.importing_model)
        lifecycleScope.launch {
            val ok = withContext(Dispatchers.IO) {
                try {
                    contentResolver.openInputStream(uri)?.use { input ->
                        modelFile.outputStream().use { output -> input.copyTo(output) }
                    }
                    true
                } catch (e: Exception) {
                    false
                }
            }
            if (ok) {
                Toast.makeText(this@MainActivity, R.string.import_done, Toast.LENGTH_SHORT).show()
                loadModel()
            } else {
                Toast.makeText(this@MainActivity, R.string.import_failed, Toast.LENGTH_LONG).show()
                refreshModelStatus()
            }
        }
    }

    private fun loadModel() {
        binding.modelStatus.text = getString(R.string.loading_model)
        binding.loadModelButton.isEnabled = false
        lifecycleScope.launch {
            val ok = withContext(Dispatchers.IO) { LlamaBridge.loadModel(modelFile.absolutePath) }
            binding.loadModelButton.isEnabled = true
            if (!ok) Toast.makeText(this@MainActivity, R.string.load_failed, Toast.LENGTH_LONG).show()
            refreshModelStatus()
        }
    }

    private fun runExtraction() {
        val message = binding.messageInput.text.toString().trim()
        if (message.isEmpty()) {
            Toast.makeText(this, R.string.empty_message, Toast.LENGTH_SHORT).show()
            return
        }
        val prompt = ScheduleExtractor.buildPrompt(
            channel = binding.channelInput.text.toString().ifBlank { "kakao" },
            receivedAt = binding.receivedAtInput.text.toString().ifBlank { ScheduleExtractor.nowIso() },
            sender = binding.senderInput.text.toString(),
            message = message,
        )

        binding.extractButton.isEnabled = false
        binding.resultText.text = getString(R.string.inferring)
        binding.addCalendarButton.visibility = View.GONE

        lifecycleScope.launch {
            val raw = withContext(Dispatchers.Default) { LlamaBridge.complete(prompt, nPredict = 256) }
            val ext = ScheduleExtractor.parse(raw)
            lastExtraction = ext
            renderResult(ext)
            binding.extractButton.isEnabled = true
        }
    }

    private fun renderResult(ext: Extraction) {
        val sb = StringBuilder()
        if (ext.parseError != null) {
            sb.append("⚠ JSON 파싱 실패: ").append(ext.parseError).append("\n\n")
            sb.append("raw 출력:\n").append(ext.rawJson)
            binding.resultText.text = sb.toString()
            binding.addCalendarButton.visibility = View.GONE
            return
        }
        sb.append("has_schedule: ").append(ext.hasSchedule).append("\n")
        if (!ext.hasSchedule || ext.events.isEmpty()) {
            sb.append("\n→ 등록할 일정 없음")
            binding.resultText.text = sb.toString()
            binding.addCalendarButton.visibility = View.GONE
            return
        }
        ext.events.forEachIndexed { i, e ->
            sb.append("\n[이벤트 ").append(i + 1).append("]\n")
            sb.append("제목: ").append(e.title).append("\n")
            sb.append("시작: ").append(e.start ?: "(없음)").append("\n")
            if (e.end != null) sb.append("종료: ").append(e.end).append("\n")
            if (e.location != null) sb.append("장소: ").append(e.location).append("\n")
            if (e.attendees.isNotEmpty()) sb.append("참석: ").append(e.attendees.joinToString(", ")).append("\n")
            if (e.recurrence != null) sb.append("반복: ").append(e.recurrence).append("\n")
            sb.append("신뢰도: ").append(e.confidence).append("\n")
        }
        binding.resultText.text = sb.toString()
        // MVP: 첫 이벤트만 캘린더 버튼으로. (multi-event는 추후 리스트로 확장)
        binding.addCalendarButton.visibility = View.VISIBLE
    }

    private fun addToCalendar() {
        val ext = lastExtraction ?: return
        val event = ext.events.firstOrNull() ?: return
        try {
            CalendarInserter.launch(this, event)
        } catch (e: Exception) {
            Toast.makeText(this, getString(R.string.calendar_failed, e.message), Toast.LENGTH_LONG).show()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) LlamaBridge.free()
    }
}
