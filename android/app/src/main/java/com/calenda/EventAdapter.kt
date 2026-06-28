package com.calenda

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.calenda.databinding.ItemEventBinding
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 메인·이벤트함 카드 공용 어댑터. 버튼 세 개:
 *   [소스]            — 원본 앱(SMS/카톡/Gmail) 열기.
 *   [삭제]            — 이벤트함에서 제거(등록돼 있으면 캘린더 일정도 함께 삭제).
 *   [등록 / 캘린더]   — 미등록이면 캘린더 등록, 등록됨이면 Google Calendar 앱에서 열기.
 * 카드 본문 탭 → 편집 화면.
 */
class EventAdapter(
    private val onDelete: (DetectedEvent) -> Unit,
    private val onRegister: (DetectedEvent) -> Unit,
    private val onEdit: (DetectedEvent) -> Unit,
    private val onSource: (DetectedEvent) -> Unit = {},
    private val onCalendar: (DetectedEvent) -> Unit = {},
) : ListAdapter<DetectedEvent, EventAdapter.VH>(DIFF) {

    inner class VH(val b: ItemEventBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemEventBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val e = getItem(position)
        val ctx = holder.b.root.context
        val b = holder.b

        b.eventTitle.text = e.title
        b.eventTime.text = prettyTime(e.start, e.allDay)

        if (e.location.isNullOrBlank()) {
            b.eventLocation.visibility = View.GONE
        } else {
            b.eventLocation.visibility = View.VISIBLE
            b.eventLocation.text = e.location
        }

        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        val chLabel = when (e.channel) { "sms" -> "SMS"; "kakao" -> "카톡"; "gmail" -> "Gmail"; else -> e.channel }
        b.eventMeta.text = buildString {
            append(chLabel).append(" · ").append(formatReceived(e.receivedAt, e.createdAt))
            if (registered) append(" · 등록됨")
        }

        // [소스]: 원본 앱 열기
        b.btnSource.text = ctx.getString(R.string.act_source)
        b.btnSource.setOnClickListener { onSource(e) }

        // [삭제]
        b.btnPrimary.text = ctx.getString(R.string.act_delete)
        b.btnPrimary.setOnClickListener { onDelete(e) }

        // [캘린더](등록됨) 또는 [등록](미등록)
        if (registered) {
            b.btnSecondary.text = ctx.getString(R.string.act_calendar_view)
            b.btnSecondary.setOnClickListener { onCalendar(e) }
        } else {
            b.btnSecondary.text = ctx.getString(R.string.act_add)
            b.btnSecondary.setOnClickListener { onRegister(e) }
        }
        b.btnSecondary.isEnabled = true

        // 편집: 카드 본문 탭.
        b.root.setOnClickListener { onEdit(e) }
    }

    private fun prettyTime(start: String?, allDay: Boolean): String {
        if (start.isNullOrBlank()) return "(시간 미정)"
        val src = listOf("yyyy-MM-dd'T'HH:mm:ssXXX", "yyyy-MM-dd'T'HH:mmXXX", "yyyy-MM-dd")
        for (p in src) {
            try {
                val d: Date = SimpleDateFormat(p, Locale.KOREA).parse(start) ?: continue
                val out = if (allDay) "M월 d일 (E)" else "M월 d일 (E) HH:mm"
                return SimpleDateFormat(out, Locale.KOREA).format(d)
            } catch (_: Exception) { /* try next */ }
        }
        return start
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<DetectedEvent>() {
            override fun areItemsTheSame(a: DetectedEvent, b: DetectedEvent) = a.id == b.id
            override fun areContentsTheSame(a: DetectedEvent, b: DetectedEvent) = a == b
        }
    }
}
