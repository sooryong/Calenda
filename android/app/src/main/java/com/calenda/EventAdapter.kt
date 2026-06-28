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
 * 메인·이벤트함 카드 공용 어댑터.
 *   카드 본문 탭      — 원본 앱(SMS/카톡/Gmail) 열기.
 *   [삭제]            — 일정 자체를 제거(등록돼 있으면 캘린더 일정도 함께 삭제).
 *   [등록하기/등록취소] — 미등록이면 캘린더 등록, 등록됨이면 등록 취소(캘린더에서 제거, 이벤트함엔 유지).
 * 본문: 제목 · 시간 · 발신자(필수) · 장소(있으면) · 설명(있으면) · 채널/수신시각/상태.
 */
class EventAdapter(
    private val onDelete: (DetectedEvent) -> Unit,
    private val onRegister: (DetectedEvent) -> Unit,
    private val onSource: (DetectedEvent) -> Unit = {},
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

        // 발신자: 필수 표시
        b.eventSender.text = ctx.getString(R.string.card_sender_fmt, e.sender.ifBlank { "—" })

        // 장소: 있으면
        if (e.location.isNullOrBlank()) {
            b.eventLocation.visibility = View.GONE
        } else {
            b.eventLocation.visibility = View.VISIBLE
            b.eventLocation.text = ctx.getString(R.string.card_location_fmt, e.location)
        }

        // 설명: 있으면
        if (e.description.isNullOrBlank()) {
            b.eventDescription.visibility = View.GONE
        } else {
            b.eventDescription.visibility = View.VISIBLE
            b.eventDescription.text = e.description
        }

        val registered = e.status == EventStatus.ADDED || e.status == EventStatus.AUTO_ADDED
        val chLabel = when (e.channel) { "sms" -> "SMS"; "kakao" -> "카톡"; "gmail" -> "Gmail"; else -> e.channel }
        b.eventMeta.text = buildString {
            append(chLabel).append(" · ").append(formatReceived(e.receivedAt, e.createdAt))
            if (registered) append(" · 등록됨")
        }

        // [삭제]: 일정 자체 제거
        b.btnPrimary.text = ctx.getString(R.string.act_delete)
        b.btnPrimary.setOnClickListener { onDelete(e) }

        // [등록취소](등록됨) 또는 [등록하기](미등록)
        b.btnSecondary.text =
            ctx.getString(if (registered) R.string.act_unregister else R.string.act_register)
        b.btnSecondary.setOnClickListener { onRegister(e) }
        b.btnSecondary.isEnabled = true

        // 카드 본문 탭 → 원본 메시지 앱 열기.
        b.root.setOnClickListener { onSource(e) }
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
