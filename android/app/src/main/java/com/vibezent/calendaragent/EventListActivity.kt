package com.vibezent.calendaragent

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import com.vibezent.calendaragent.databinding.ActivityEventListBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 이벤트함: 감지된 일정 목록. Room Flow를 관찰해 자동 갱신.
 * 상태별 액션(추가/무시/되돌리기/다시추가)을 처리하고 캘린더·DB에 반영한다.
 */
class EventListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityEventListBinding
    private val repo by lazy { EventRepository.from(this) }
    private val adapter = EventAdapter(onDelete = ::onDelete, onRegister = ::onRegister, onEdit = ::onEdit)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityEventListBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.recycler.layoutManager = LinearLayoutManager(this)
        binding.recycler.adapter = adapter

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                repo.all.collect { list ->
                    adapter.submitList(list)
                    binding.emptyView.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
                }
            }
        }
    }

    /** 삭제: 등록됨이면 캘린더에서도 삭제(확인), 미등록이면 제안 폐기. 카드는 사라짐(DISMISSED). */
    private fun onDelete(e: DetectedEvent) {
        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        if (registered) {
            AlertDialog.Builder(this)
                .setTitle(R.string.delete_cal_title)
                .setMessage(R.string.delete_cal_msg)
                .setPositiveButton(R.string.dialog_delete) { _, _ -> doDelete(e, deleteCal = true) }
                .setNegativeButton(R.string.dialog_cancel, null)
                .show()
        } else {
            doDelete(e, deleteCal = false)
        }
    }

    private fun doDelete(e: DetectedEvent, deleteCal: Boolean) {
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                if (deleteCal) e.calendarEventId?.let { CalendarWriter.delete(this@EventListActivity, it) }
                repo.setStatus(e.id, EventStatus.DISMISSED, null)
            }
        }
    }

    /** 등록 토글: 미등록→캘린더 추가, 등록됨→캘린더에서 빼고 미등록(이벤트함엔 유지). */
    private fun onRegister(e: DetectedEvent) {
        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        if (!registered) { addToCalendar(e); return }
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                e.calendarEventId?.let { CalendarWriter.delete(this@EventListActivity, it) }
                repo.setStatus(e.id, EventStatus.PENDING, null)
            }
        }
    }

    /** 편집: 편집 화면 열기. */
    private fun onEdit(e: DetectedEvent) {
        startActivity(Intent(this, EventEditActivity::class.java).putExtra(EventEditActivity.EXTRA_ID, e.id))
    }

    private fun addToCalendar(e: DetectedEvent) {
        lifecycleScope.launch {
            if (CalendarWriter.hasPermission(this@EventListActivity)) {
                val calId = withContext(Dispatchers.IO) {
                    CalendarWriter.insert(this@EventListActivity, e.toCalendarEvent())
                }
                if (calId != null) {
                    repo.setStatus(e.id, EventStatus.ADDED, calId)
                } else {
                    Toast.makeText(this@EventListActivity, R.string.calendar_add_failed, Toast.LENGTH_SHORT).show()
                }
            } else {
                // 권한 없으면 시스템 캘린더 UI로 위임(사용자가 저장 완료). 상태는 그대로 둠.
                try {
                    CalendarInserter.launch(this@EventListActivity, e.toCalendarEvent())
                    Toast.makeText(this@EventListActivity, R.string.inbox_no_calendar, Toast.LENGTH_SHORT).show()
                } catch (ex: Exception) {
                    Toast.makeText(this@EventListActivity, R.string.calendar_add_failed, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

}
