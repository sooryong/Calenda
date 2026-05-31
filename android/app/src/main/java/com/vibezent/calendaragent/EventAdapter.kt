package com.vibezent.calendaragent

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.vibezent.calendaragent.databinding.ItemEventBinding
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 이벤트함 목록 어댑터. 상태별로 두 액션 버튼(주/보조)을 다르게 표시:
 *   PENDING   → [캘린더에 추가] [무시]
 *   ADDED/AUTO→ [되돌리기]  (보조 숨김)
 *   DISMISSED → [다시 추가]  (보조 숨김)
 */
class EventAdapter(
    private val onPrimary: (DetectedEvent) -> Unit,
    private val onSecondary: (DetectedEvent) -> Unit,
    private val onEdit: (DetectedEvent) -> Unit,
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

        b.statusBadge.text = when (e.status) {
            EventStatus.PENDING -> ctx.getString(R.string.status_pending)
            EventStatus.ADDED -> ctx.getString(R.string.status_added)
            EventStatus.AUTO_ADDED -> ctx.getString(R.string.status_auto)
            EventStatus.DISMISSED -> ctx.getString(R.string.status_dismissed)
        }
        b.eventTitle.text = e.title
        b.eventTime.text = prettyTime(e.start, e.allDay)

        if (e.location.isNullOrBlank()) {
            b.eventLocation.visibility = View.GONE
        } else {
            b.eventLocation.visibility = View.VISIBLE
            b.eventLocation.text = "📍 ${e.location}"
        }

        val conf = (e.confidence * 100).toInt()
        b.eventMeta.text = "${e.channel} · ${e.sender} · 신뢰도 ${conf}%"

        when (e.status) {
            EventStatus.PENDING -> {
                b.btnPrimary.visibility = View.VISIBLE
                b.btnPrimary.text = ctx.getString(R.string.act_add)
                b.btnSecondary.visibility = View.VISIBLE
                b.btnSecondary.text = ctx.getString(R.string.act_dismiss)
            }
            EventStatus.ADDED, EventStatus.AUTO_ADDED -> {
                b.btnPrimary.visibility = View.VISIBLE
                b.btnPrimary.text = ctx.getString(R.string.act_undo)
                b.btnSecondary.visibility = View.GONE
            }
            EventStatus.DISMISSED -> {
                b.btnPrimary.visibility = View.VISIBLE
                b.btnPrimary.text = ctx.getString(R.string.act_readd)
                b.btnSecondary.visibility = View.GONE
            }
        }
        b.btnPrimary.setOnClickListener { onPrimary(e) }
        b.btnSecondary.setOnClickListener { onSecondary(e) }
        b.btnEdit.setOnClickListener { onEdit(e) }
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
