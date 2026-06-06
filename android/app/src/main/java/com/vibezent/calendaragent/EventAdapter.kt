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
 * 이벤트함 목록 어댑터. 버튼은 항상 [삭제][등록] 두 개:
 *   미등록(PENDING/DISMISSED) → [삭제](폐기) [등록](활성)
 *   등록됨(ADDED/AUTO_ADDED)   → [삭제](캘린더에서도 삭제) [등록](회색 비활성=이미 등록)
 * 카드 본문 탭 → 편집 화면(시간·제목·장소 수정 후 등록/삭제).
 */
class EventAdapter(
    private val onDelete: (DetectedEvent) -> Unit,
    private val onRegister: (DetectedEvent) -> Unit,
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

        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED

        // 삭제: 항상 활성. (등록됨이면 핸들러가 캘린더 삭제까지 확인 후 수행)
        b.btnPrimary.text = ctx.getString(R.string.act_delete)
        b.btnPrimary.setOnClickListener { onDelete(e) }

        // 등록: 미등록이면 활성, 등록됨이면 회색 비활성(이미 등록 표시).
        b.btnSecondary.text = ctx.getString(R.string.act_add)
        b.btnSecondary.isEnabled = !registered
        b.btnSecondary.setOnClickListener { onRegister(e) }

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
