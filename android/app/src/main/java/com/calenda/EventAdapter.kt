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
 * 메인·이벤트함 카드 공용 어댑터. 버튼 두 개:
 *   [삭제]            — 이벤트함에서 제거(등록돼 있으면 캘린더 일정도 함께 삭제).
 *   [등록 ↔ 등록 취소] — 캘린더 등록 토글. 미등록=등록, 등록됨=등록 취소(이벤트함엔 그대로 남음).
 * 카드 본문 탭 → 편집 화면.
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

        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        // 메타: 채널 · 수신시각 · 신뢰도 [· 등록됨]. (발신자는 제목에 포함되므로 생략. 예비는 상태 표시 없음.)
        val conf = (e.confidence * 100).toInt()
        val chLabel = when (e.channel) { "sms" -> "SMS"; "kakao" -> "카톡"; "gmail" -> "Gmail"; else -> e.channel }
        b.eventMeta.text = buildString {
            append(chLabel).append(" · ").append(formatReceived(e.receivedAt, e.createdAt))
            append(" · 신뢰도 ").append(conf).append("%")
            if (registered) append(" · 등록됨")
        }

        // 주 버튼 [삭제]: 메인=메인서 제거(+등록취소), 이벤트함=완전삭제. 동작은 화면 핸들러가 결정.
        b.btnPrimary.text = ctx.getString(R.string.act_delete)
        b.btnPrimary.setOnClickListener { onDelete(e) }

        // 등록 ↔ 등록 취소 토글 (등록됨이면 '등록 취소'). 실제 분기는 핸들러가 상태로 처리.
        b.btnSecondary.text = ctx.getString(if (registered) R.string.act_unregister else R.string.act_add)
        b.btnSecondary.isEnabled = true
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
