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
import com.vibezent.calendaragent.databinding.ActivityDebugBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * 디버그/개발 화면 (설정 → "디버그: 수동 추출"에서 진입).
 * 모델 임포트·로드 상태 점검 + 메시지 수동 입력으로 추출 파이프라인을 테스트한다.
 * 실사용 메인 화면(MainActivity 대시보드)에서 분리해 둔 도구.
 */
class DebugActivity : AppCompatActivity() {

    private lateinit var binding: ActivityDebugBinding
    private var lastEvents: List<CalendarEvent> = emptyList()

    private val modelFile: File get() = ModelStore.modelFile(this)

    private val requestPerms = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { refreshCollectStatus() }

    private val pickModel = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { res -> if (res.resultCode == Activity.RESULT_OK) res.data?.data?.let { importModel(it) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityDebugBinding.inflate(layoutInflater)
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

        binding.notifAccessButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        binding.smsPermButton.setOnClickListener {
            requestPerms.launch(arrayOf(
                Manifest.permission.RECEIVE_SMS,
                Manifest.permission.POST_NOTIFICATIONS,
                Manifest.permission.READ_CALENDAR,
                Manifest.permission.WRITE_CALENDAR,
            ))
        }
    }

    override fun onResume() {
        super.onResume()
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
        binding.reimportButton.visibility = if (modelFile.exists()) View.VISIBLE else View.GONE
        refreshModelVersion()
    }

    /** 설치된 gguf의 버전명(general.name)과 업로드 시각(파일 수정시각)을 표시. */
    private fun refreshModelVersion() {
        if (!modelFile.exists()) {
            binding.modelVersion.visibility = View.GONE
            return
        }
        val info = GgufInfo.read(modelFile)
        val name = info.name ?: getString(R.string.model_version_unknown)
        val date = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.KOREA)
            .format(java.util.Date(info.lastModified))
        binding.modelVersion.text = getString(R.string.model_version_fmt, name, date)
        binding.modelVersion.visibility = View.VISIBLE
    }

    private fun pickModelFile() {
        pickModel.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
        })
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
                Toast.makeText(this@DebugActivity, R.string.import_done, Toast.LENGTH_SHORT).show()
                loadModel()
            } else {
                Toast.makeText(this@DebugActivity, R.string.import_failed, Toast.LENGTH_LONG).show()
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
            if (!ok) Toast.makeText(this@DebugActivity, R.string.load_failed, Toast.LENGTH_LONG).show()
            refreshModelStatus()
        }
    }

    private fun runExtraction() {
        val message = binding.messageInput.text.toString().trim()
        if (message.isEmpty()) {
            Toast.makeText(this, R.string.empty_message, Toast.LENGTH_SHORT).show()
            return
        }
        val channel = binding.channelInput.text.toString().ifBlank { "kakao" }
        val receivedAt = binding.receivedAtInput.text.toString().ifBlank { ScheduleExtractor.nowIso() }
        val sender = binding.senderInput.text.toString()
        val prompt = ScheduleExtractor.buildPrompt(channel, receivedAt, sender, message)

        binding.extractButton.isEnabled = false
        binding.resultText.text = getString(R.string.inferring)
        binding.addCalendarButton.visibility = View.GONE

        lifecycleScope.launch {
            val raw = withContext(Dispatchers.Default) { LlamaBridge.complete(prompt, nPredict = 256) }
            val ext = ScheduleExtractor.parse(raw)
            lastEvents = ext.events.map { DateResolver.resolveEvent(receivedAt, sender, it) }
            renderResult(ext, lastEvents)
            if (ext.parseError == null && ext.hasSchedule && lastEvents.isNotEmpty()) {
                EventRepository.from(this@DebugActivity).save(
                    lastEvents.first(), channel, sender, message, EventStatus.PENDING,
                    receivedAt = receivedAt, modelRawJson = ext.rawJson, threadJson = null,
                )
            }
            binding.extractButton.isEnabled = true
        }
    }

    private fun renderResult(ext: Extraction, events: List<CalendarEvent>) {
        val sb = StringBuilder()
        if (ext.parseError != null) {
            sb.append("⚠ JSON 파싱 실패: ").append(ext.parseError).append("\n\n")
            sb.append("raw 출력:\n").append(ext.rawJson)
            binding.resultText.text = sb.toString()
            binding.addCalendarButton.visibility = View.GONE
            return
        }
        sb.append("has_schedule: ").append(ext.hasSchedule).append("\n")
        if (!ext.hasSchedule || events.isEmpty()) {
            sb.append("\n→ 등록할 일정 없음")
            binding.resultText.text = sb.toString()
            binding.addCalendarButton.visibility = View.GONE
            return
        }
        events.forEachIndexed { i, e ->
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
        binding.addCalendarButton.visibility = View.VISIBLE
    }

    private fun addToCalendar() {
        val event = lastEvents.firstOrNull() ?: return
        try {
            CalendarInserter.launch(this, event)
        } catch (e: Exception) {
            Toast.makeText(this, getString(R.string.calendar_failed, e.message), Toast.LENGTH_LONG).show()
        }
    }
}
