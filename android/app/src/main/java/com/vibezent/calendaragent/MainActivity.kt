package com.vibezent.calendaragent

import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import com.vibezent.calendaragent.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * 메인 대시보드 '오늘 받은 일정':
 *   - 상단: 채널별 '등록' 현황 칩(테마색)
 *   - 한 목록에 [예비](미등록·일정 오늘 이후) + [오늘 등록]된 건을 통합, 상태 배지+액션
 *   - 예비: 등록/편집/무시 · 등록: 취소/편집. 등록하면 같은 자리에서 배지가 [등록]으로 전환.
 *   - 예비는 일정 날짜가 지나면 자동 삭제(purgePastPending).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val repo by lazy { EventRepository.from(this) }
    private val adapter = EventAdapter(::onPrimary, ::onSecondary, ::onEdit)
    private val dateFmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.eventList.layoutManager = LinearLayoutManager(this)
        binding.eventList.adapter = adapter
        binding.settingsButton.setOnClickListener { startActivity(Intent(this, SettingsActivity::class.java)) }
        binding.allInboxButton.setOnClickListener { startActivity(Intent(this, EventListActivity::class.java)) }

        val today = dateFmt.format(Date())
        lifecycleScope.launch {
            withContext(Dispatchers.IO) { repo.purgePastPending(today) }  // 지난 예비 정리
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(repo.activeCandidates(today), repo.registeredSince(startOfToday())) { c, r -> c to r }
                    .collect { (candidates, registered) -> render(candidates, registered) }
            }
        }

        if (!SettingsStore.from(this).onboardingDone) {
            startActivity(Intent(this, OnboardingActivity::class.java))
        }
    }

    private fun render(candidates: List<DetectedEvent>, registered: List<DetectedEvent>) {
        // 채널별 '등록' 현황 칩
        chip(binding.chipKakao, getString(R.string.dash_ch_kakao), registered.count { it.channel == "kakao" })
        chip(binding.chipSms, getString(R.string.dash_ch_sms), registered.count { it.channel == "sms" })
        chip(binding.chipGmail, getString(R.string.dash_ch_gmail), registered.count { it.channel == "gmail" })

        // 예비 먼저(확인 필요), 그다음 오늘 등록
        val list = candidates + registered
        adapter.submitList(list)
        binding.emptyView.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
    }

    /** 채널 칩: "카톡 N". 등록>0이면 테마 보라, 0이면 흐림. */
    private fun chip(tv: TextView, label: String, n: Int) {
        tv.text = getString(R.string.dash_chip, label, n)
        val color = if (n > 0) R.color.purple_500 else R.color.chip_zero
        tv.backgroundTintList = ColorStateList.valueOf(ContextCompat.getColor(this, color))
    }

    private fun startOfToday(): Long = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }.timeInMillis

    // ── 목록 액션 ─────────────────────────────
    private fun onPrimary(e: DetectedEvent) {
        when (e.status) {
            EventStatus.PENDING, EventStatus.DISMISSED -> addToCalendar(e)   // 등록
            EventStatus.ADDED, EventStatus.AUTO_ADDED -> undo(e)             // 취소
        }
    }

    private fun onSecondary(e: DetectedEvent) {  // 무시
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
