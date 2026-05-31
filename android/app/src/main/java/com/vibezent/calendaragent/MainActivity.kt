package com.vibezent.calendaragent

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import com.vibezent.calendaragent.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar

/**
 * 메인 대시보드: '오늘' 감지된 일정을 채널(카톡/문자/Gmail) 요약 + 후보(확인 필요)·등록됨 목록으로 표시.
 * 모델/수동입력 등 개발 도구는 설정 → 디버그로 분리. 전체 이력은 이벤트함(EventListActivity).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val repo by lazy { EventRepository.from(this) }
    private val candidatesAdapter = EventAdapter(::onPrimary, ::onSecondary, ::onEdit)
    private val addedAdapter = EventAdapter(::onPrimary, ::onSecondary, ::onEdit)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.candidatesList.layoutManager = LinearLayoutManager(this)
        binding.candidatesList.adapter = candidatesAdapter
        binding.addedList.layoutManager = LinearLayoutManager(this)
        binding.addedList.adapter = addedAdapter

        binding.settingsButton.setOnClickListener { startActivity(Intent(this, SettingsActivity::class.java)) }
        binding.allInboxButton.setOnClickListener { startActivity(Intent(this, EventListActivity::class.java)) }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                repo.since(startOfToday()).collect { today -> render(today) }
            }
        }

        // 첫 실행이면 설정 가이드로 안내
        if (!SettingsStore.from(this).onboardingDone) {
            startActivity(Intent(this, OnboardingActivity::class.java))
        }
    }

    private fun render(today: List<DetectedEvent>) {
        val candidates = today.filter { it.status == EventStatus.PENDING }
        val added = today.filter { it.status == EventStatus.ADDED || it.status == EventStatus.AUTO_ADDED }

        fun count(ch: String) = today.count { it.status != EventStatus.DISMISSED && it.channel == ch }
        binding.channelSummary.text = getString(R.string.dash_channel_summary, count("kakao"), count("sms"), count("gmail"))

        binding.candidatesHeader.text = getString(R.string.dash_candidates, candidates.size)
        candidatesAdapter.submitList(candidates)
        binding.candidatesEmpty.visibility = if (candidates.isEmpty()) View.VISIBLE else View.GONE

        binding.addedHeader.text = getString(R.string.dash_added, added.size)
        addedAdapter.submitList(added)
        binding.addedEmpty.visibility = if (added.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun startOfToday(): Long = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }.timeInMillis

    // ── 목록 액션 (이벤트함과 동일) ─────────────────────────────
    private fun onPrimary(e: DetectedEvent) {
        when (e.status) {
            EventStatus.PENDING, EventStatus.DISMISSED -> addToCalendar(e)
            EventStatus.ADDED, EventStatus.AUTO_ADDED -> undo(e)
        }
    }

    private fun onSecondary(e: DetectedEvent) {
        lifecycleScope.launch { withContext(Dispatchers.IO) { repo.setStatus(e.id, EventStatus.DISMISSED, null) } }
    }

    private fun onEdit(e: DetectedEvent) {
        startActivity(Intent(this, EventEditActivity::class.java).putExtra(EventEditActivity.EXTRA_ID, e.id))
    }

    private fun addToCalendar(e: DetectedEvent) {
        lifecycleScope.launch {
            if (CalendarWriter.hasPermission(this@MainActivity)) {
                val calId = withContext(Dispatchers.IO) { CalendarWriter.insert(this@MainActivity, e.toCalendarEvent()) }
                if (calId != null) repo.setStatus(e.id, EventStatus.ADDED, calId)
                else Toast.makeText(this@MainActivity, R.string.calendar_add_failed, Toast.LENGTH_SHORT).show()
            } else {
                try {
                    CalendarInserter.launch(this@MainActivity, e.toCalendarEvent())
                    Toast.makeText(this@MainActivity, R.string.inbox_no_calendar, Toast.LENGTH_SHORT).show()
                } catch (ex: Exception) {
                    Toast.makeText(this@MainActivity, R.string.calendar_add_failed, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun undo(e: DetectedEvent) {
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                e.calendarEventId?.let { CalendarWriter.delete(this@MainActivity, it) }
                repo.setStatus(e.id, EventStatus.DISMISSED, null)
            }
        }
    }
}
