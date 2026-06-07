package com.vibezent.calendaragent

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.widget.addTextChangedListener
import androidx.lifecycle.lifecycleScope
import com.vibezent.calendaragent.databinding.ActivityEventEditBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/**
 * 감지 일정 편집: 제목·날짜·시간·장소·참석자·메모 수정 후 저장(+캘린더 추가).
 * 저장 시 (1) 이벤트함 행 갱신, (2) editedJson(교정 gold) 기록 → incremental learning 최우선 신호,
 * (3) 캘린더 등록. editedJson은 토큰 스키마(절대일자 + 12h marker)로 적어 resolver가 그대로 재현 가능.
 */
class EventEditActivity : AppCompatActivity() {

    private lateinit var binding: ActivityEventEditBinding
    private val repo by lazy { EventRepository.from(this) }
    private val cal: Calendar = Calendar.getInstance()
    private var current: DetectedEvent? = null
    private var registered = false          // 등록된 일정인가(ADDED/AUTO_ADDED)
    private var initialSig: String? = null  // 로드 직후 폼 스냅샷 — 변경 감지(업데이트 버튼 활성화)용

    private val dateFmt = SimpleDateFormat("yyyy-MM-dd", Locale.KOREA)
    private val timeFmt = SimpleDateFormat("HH:mm", Locale.KOREA)
    private val isoFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityEventEditBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val id = intent.getLongExtra(EXTRA_ID, -1L)
        if (id < 0) { finish(); return }

        binding.btnDate.setOnClickListener { pickDate() }
        binding.btnTime.setOnClickListener { pickTime() }
        binding.allDayCheck.setOnCheckedChangeListener { _, checked ->
            binding.btnTime.isEnabled = !checked
            refreshButtons()
        }
        binding.saveButton.setOnClickListener { save() }
        binding.deleteButton.setOnClickListener { onDelete() }

        // 변경 감지 → [업데이트] 활성/비활성 (예정 일정의 [등록]은 항상 활성).
        binding.editTitle.addTextChangedListener { onFormChanged() }
        binding.editLocation.addTextChangedListener { onFormChanged() }
        binding.editAttendees.addTextChangedListener { onFormChanged() }
        binding.editDescription.addTextChangedListener { onFormChanged() }

        lifecycleScope.launch {
            val e = withContext(Dispatchers.IO) { repo.get(id) }
            if (e == null) { finish(); return@launch }
            current = e
            populate(e)
        }
    }

    private fun populate(e: DetectedEvent) {
        binding.editTitle.setText(e.title)
        binding.editLocation.setText(e.location ?: "")
        binding.editAttendees.setText(e.attendees.joinToString(", "))
        binding.editDescription.setText(e.description ?: "")
        binding.allDayCheck.isChecked = e.allDay
        binding.btnTime.isEnabled = !e.allDay
        parseInto(cal, e.start)
        refreshButtons()

        // 읽기전용 메타: 채널 · 수신시각 · 신뢰도 (카드와 동일 정보)
        val chLabel = when (e.channel) { "sms" -> "SMS"; "kakao" -> "카톡"; "gmail" -> "Gmail"; else -> e.channel }
        binding.editMeta.text =
            "$chLabel · ${formatReceived(e.receivedAt, e.createdAt)} 수신 · 신뢰도 ${(e.confidence * 100).toInt()}%"

        registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        binding.statusLabel.text =
            getString(if (registered) R.string.edit_status_registered else R.string.edit_status_scheduled)
        binding.statusLabel.setTextColor(
            ContextCompat.getColor(this, if (registered) R.color.purple_500 else R.color.amber_600),
        )
        // 예정 → [등록](항상 활성). 등록됨 → [업데이트](변경 있을 때만 활성).
        binding.saveButton.text = getString(if (registered) R.string.act_update else R.string.act_add)
        initialSig = formSig()
        binding.saveButton.isEnabled = !registered
    }

    /** 폼 전체 스냅샷 문자열 — initialSig와 비교해 변경 여부 판정. */
    private fun formSig(): String = listOf(
        binding.editTitle.text.toString().trim(),
        binding.editLocation.text.toString().trim(),
        binding.editAttendees.text.toString().trim(),
        binding.editDescription.text.toString().trim(),
        binding.allDayCheck.isChecked.toString(),
        dateFmt.format(cal.time),
        if (binding.allDayCheck.isChecked) "" else timeFmt.format(cal.time),
    ).joinToString("")

    /** 등록된 일정이면 변경 있을 때만 [업데이트] 활성화. 예정이면 [등록]은 늘 활성. */
    private fun onFormChanged() {
        if (initialSig == null) return  // populate 중 refreshButtons 호출은 무시
        binding.saveButton.isEnabled = if (registered) formSig() != initialSig else true
    }

    private fun parseInto(c: Calendar, iso: String?) {
        if (iso.isNullOrBlank()) return
        for (p in listOf("yyyy-MM-dd'T'HH:mm:ssXXX", "yyyy-MM-dd'T'HH:mmXXX", "yyyy-MM-dd")) {
            try {
                val d = SimpleDateFormat(p, Locale.US).parse(iso) ?: continue
                c.time = d
                return
            } catch (_: Exception) { /* try next */ }
        }
    }

    private fun refreshButtons() {
        binding.btnDate.text = dateFmt.format(cal.time)
        binding.btnTime.text = if (binding.allDayCheck.isChecked) getString(R.string.all_day) else timeFmt.format(cal.time)
        onFormChanged()
    }

    private fun pickDate() {
        DatePickerDialog(
            this,
            { _, y, m, d -> cal.set(Calendar.YEAR, y); cal.set(Calendar.MONTH, m); cal.set(Calendar.DAY_OF_MONTH, d); refreshButtons() },
            cal.get(Calendar.YEAR), cal.get(Calendar.MONTH), cal.get(Calendar.DAY_OF_MONTH),
        ).show()
    }

    private fun pickTime() {
        TimePickerDialog(
            this,
            { _, h, min -> cal.set(Calendar.HOUR_OF_DAY, h); cal.set(Calendar.MINUTE, min); refreshButtons() },
            cal.get(Calendar.HOUR_OF_DAY), cal.get(Calendar.MINUTE), true,
        ).show()
    }

    private fun save() {
        val cur = current ?: return
        val title = binding.editTitle.text.toString().trim().ifBlank { "일정" }
        val loc = binding.editLocation.text.toString().trim().ifBlank { null }
        val attendees = binding.editAttendees.text.toString()
            .split(",").map { it.trim() }.filter { it.isNotEmpty() }
        val desc = binding.editDescription.text.toString().trim().ifBlank { null }
        val allDay = binding.allDayCheck.isChecked
        val startIso = if (allDay) dateFmt.format(cal.time) else isoFmt.format(cal.time)

        val ce = CalendarEvent(title, startIso, null, allDay, loc, attendees, desc, cur.recurrence, 1.0)
        val edited = buildEditedJson(cur, title, allDay, loc, attendees, desc)

        // 경로 2: 사용자가 location을 지웠다면(오추출 교정) 그 발신자에 대해 '장소 아님'으로 학습.
        val oldLoc = cur.location
        if (loc == null && !oldLoc.isNullOrBlank()) {
            AliasStore.from(this).markNotPlace(cur.sender, oldLoc)
        }

        // 등록됨 → 기존 캘린더 일정 제자리 수정([업데이트]). 예정 → 새로 등록([등록]).
        val isUpdate = registered && cur.calendarEventId != null
        lifecycleScope.launch {
            val calId = withContext(Dispatchers.IO) {
                when {
                    !CalendarWriter.hasPermission(this@EventEditActivity) -> null
                    isUpdate -> if (CalendarWriter.update(this@EventEditActivity, cur.calendarEventId!!, ce)) cur.calendarEventId else null
                    else -> CalendarWriter.insert(this@EventEditActivity, ce)
                }
            }
            val row = cur.copy(
                title = title, start = startIso, end = null, allDay = allDay,
                location = loc, attendees = attendees, description = desc, editedJson = edited,
                status = if (calId != null) EventStatus.ADDED else cur.status,
                calendarEventId = calId ?: cur.calendarEventId,
                registeredAt = if (calId != null && !isUpdate) System.currentTimeMillis() else cur.registeredAt,
            )
            withContext(Dispatchers.IO) { repo.update(row) }
            if (calId == null && !isUpdate) {
                // 신규 등록인데 권한 없음/실패 → 시스템 캘린더 UI로 위임 (업데이트 실패는 위임 안 함=중복 방지)
                try { CalendarInserter.launch(this@EventEditActivity, ce) } catch (_: Exception) {}
            }
            Toast.makeText(this@EventEditActivity, R.string.saved, Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    /** 삭제: 등록됨이면 캘린더에서도 삭제(확인), 미등록이면 제안 폐기. 둘 다 DISMISSED 처리 후 종료. */
    private fun onDelete() {
        val cur = current ?: return
        val registered = cur.status == EventStatus.ADDED || cur.status == EventStatus.AUTO_ADDED
        if (registered) {
            AlertDialog.Builder(this)
                .setTitle(R.string.delete_cal_title)
                .setMessage(R.string.delete_cal_msg)
                .setPositiveButton(R.string.dialog_delete) { _, _ -> doDelete(cur, deleteCal = true) }
                .setNegativeButton(R.string.dialog_cancel, null)
                .show()
        } else {
            doDelete(cur, deleteCal = false)
        }
    }

    private fun doDelete(e: DetectedEvent, deleteCal: Boolean) {
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                if (deleteCal) e.calendarEventId?.let { CalendarWriter.delete(this@EventEditActivity, it) }
                repo.setStatus(e.id, EventStatus.DISMISSED, null)
            }
            finish()
        }
    }

    /** 교정 gold(토큰 스키마). 날짜는 절대일자, 시각은 12h+marker로 적어 resolver가 정확히 재현. */
    private fun buildEditedJson(
        cur: DetectedEvent, title: String, allDay: Boolean,
        loc: String?, attendees: List<String>, desc: String?,
    ): String {
        val ev = JSONObject()
            .put("title", title)
            .put("date", dateFmt.format(cal.time))
            .put("time", if (allDay) JSONObject.NULL else timeToken(cal.get(Calendar.HOUR_OF_DAY), cal.get(Calendar.MINUTE)))
            .put("end_time", JSONObject.NULL)
            .put("all_day", allDay)
            .put("location", loc ?: JSONObject.NULL)
            .put("attendees", JSONArray(attendees))
            .put("organizer", JSONObject.NULL)
            .put("description", desc ?: JSONObject.NULL)
            .put("recurrence", cur.recurrence ?: JSONObject.NULL)
            .put("confidence", 1.0)
        return JSONObject().put("has_schedule", true).put("events", JSONArray().put(ev)).toString()
    }

    /** 24h → {hour(1~12), minute, marker} 토큰. resolver가 동일 시각으로 복원. */
    private fun timeToken(h24: Int, min: Int): JSONObject {
        val (h12, marker) = when {
            h24 == 0 -> 12 to "오전"
            h24 in 1..11 -> h24 to "오전"
            h24 == 12 -> 12 to "오후"
            else -> (h24 - 12) to "오후"
        }
        return JSONObject().put("hour", h12).put("minute", min).put("marker", marker)
    }

    companion object {
        const val EXTRA_ID = "event_id"
    }
}
