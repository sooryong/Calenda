package com.calenda

import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/**
 * "저장할 캘린더 선택" 다이얼로그 (설정·온보딩 공용).
 * 기기에 로그인된 Google 본인소유 캘린더 목록에서 고르면 SettingsStore.targetCalendarId에 저장 후 onPicked().
 * (OAuth 불필요 — OS가 이미 동기 중인 계정을 그대로 사용.)
 */
object CalendarPicker {
    fun show(activity: AppCompatActivity, onPicked: () -> Unit) {
        val cals = CalendarWriter.selectableCalendars(activity)
        if (cals.isEmpty()) {
            Toast.makeText(activity, R.string.calendar_none, Toast.LENGTH_LONG).show()
            return
        }
        val settings = SettingsStore.from(activity)
        val labels = cals.map { "${it.display}\n${it.account}" }.toTypedArray()
        val checked = cals.indexOfFirst { it.id == settings.targetCalendarId }
        AlertDialog.Builder(activity)
            .setTitle(R.string.calendar_picker_title)
            .setSingleChoiceItems(labels, checked) { dialog, which ->
                settings.targetCalendarId = cals[which].id
                dialog.dismiss()
                onPicked()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }
}
