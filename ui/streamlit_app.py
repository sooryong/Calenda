"""데이터 검수 / 에러 분석 Streamlit UI.

실행:
    streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIRS = {
    "raw": ROOT / "data" / "raw",
    "processed": ROOT / "data" / "processed",
    "eval (골든)": ROOT / "data" / "eval",
    "failures": ROOT / "data" / "failures",
}

st.set_page_config(page_title="Calendar Agent — Data Inspector", layout="wide")
st.title("📅 Calendar Agent — 데이터 검수 / 에러 분석")


# --- 사이드바: 데이터 선택 ---
st.sidebar.header("데이터 소스")
dir_key = st.sidebar.selectbox("디렉토리", list(DATA_DIRS.keys()))
data_dir = DATA_DIRS[dir_key]

files = sorted(data_dir.glob("*.jsonl"))
if not files:
    st.warning(f"{data_dir} 에 JSONL 파일이 없습니다. 먼저 데이터를 생성하세요.")
    st.stop()

selected = st.sidebar.selectbox("파일", [f.name for f in files])
path = data_dir / selected


@st.cache_data(show_spinner=False)
def load_jsonl(p: str) -> list[dict]:
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


rows = load_jsonl(str(path))
st.sidebar.metric("총 건수", len(rows))


# --- 필터 ---
st.sidebar.header("필터")
channels = sorted({r.get("channel", "?") for r in rows})
languages = sorted({r.get("language", "?") for r in rows})
has_sched_filter = st.sidebar.radio("has_schedule", ["all", "true", "false"], horizontal=True)
ch_filter = st.sidebar.multiselect("채널", channels, default=channels)
lg_filter = st.sidebar.multiselect("언어", languages, default=languages)
search = st.sidebar.text_input("메시지 검색 (부분 일치)")


def matches(r: dict) -> bool:
    if r.get("channel") not in ch_filter:
        return False
    if r.get("language") not in lg_filter:
        return False
    if has_sched_filter != "all":
        want = has_sched_filter == "true"
        if r.get("gold", {}).get("has_schedule") != want:
            return False
    if search and search not in r.get("message", ""):
        return False
    return True


filtered = [r for r in rows if matches(r)]
st.sidebar.metric("필터 후", len(filtered))


# --- 상단: 통계 요약 ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("총", len(rows))
col2.metric("일정 있음", sum(1 for r in rows if r.get("gold", {}).get("has_schedule")))
col3.metric("일정 없음", sum(1 for r in rows if not r.get("gold", {}).get("has_schedule")))
col4.metric("멀티 이벤트", sum(1 for r in rows if len(r.get("gold", {}).get("events", [])) >= 2))


# --- 본문: 두 가지 뷰 ---
tab1, tab2, tab3 = st.tabs(["🗂 페어 브라우저", "📊 분포", "❌ 실패 분석"])

with tab1:
    st.subheader("페어 단건 보기")
    if not filtered:
        st.info("필터 결과 없음")
    else:
        idx = st.number_input("인덱스", min_value=0, max_value=len(filtered) - 1, value=0, step=1)
        row = filtered[int(idx)]

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**메시지**")
            st.code(row.get("message", ""), language="text")
            st.markdown(f"- 채널: `{row.get('channel')}`")
            st.markdown(f"- 수신시각: `{row.get('received_at')}`")
            st.markdown(f"- 발신자: `{row.get('sender', '')}`")
            st.markdown(f"- 시나리오: `{row.get('scenario_id', '')}`")
        with c2:
            st.markdown("**Gold JSON**")
            st.code(json.dumps(row.get("gold", {}), ensure_ascii=False, indent=2), language="json")

        if "_qa" in row:
            st.markdown("**QA 판정**")
            st.code(json.dumps(row["_qa"], ensure_ascii=False, indent=2), language="json")

        if "_pred" in row or "_pred_raw" in row:
            st.markdown("**모델 출력**")
            if "_pred" in row:
                st.code(json.dumps(row["_pred"], ensure_ascii=False, indent=2), language="json")
            if "_pred_raw" in row:
                st.code(row["_pred_raw"], language="text")
            if "_scores" in row:
                st.markdown("**점수**")
                st.json(row["_scores"])

with tab2:
    st.subheader("분포")
    df = pd.DataFrame(
        [
            {
                "channel": r.get("channel"),
                "language": r.get("language"),
                "has_schedule": r.get("gold", {}).get("has_schedule"),
                "n_events": len(r.get("gold", {}).get("events", [])),
                "msg_len": len(r.get("message", "")),
                "scenario_id": r.get("scenario_id", ""),
            }
            for r in rows
        ]
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**채널 × has_schedule**")
        st.bar_chart(df.groupby(["channel", "has_schedule"]).size().unstack(fill_value=0))
    with c2:
        st.markdown("**언어 × has_schedule**")
        st.bar_chart(df.groupby(["language", "has_schedule"]).size().unstack(fill_value=0))

    st.markdown("**메시지 길이 분포**")
    st.bar_chart(df["msg_len"].value_counts(bins=20).sort_index())

with tab3:
    st.subheader("실패 케이스 분석")
    failed = [r for r in filtered if "_scores" in r or "_pred_raw" in r or "_reason" in r]
    if not failed:
        st.info("이 파일에는 실패 케이스가 없습니다. data/failures/ 의 파일을 선택해보세요.")
    else:
        df_fail = pd.DataFrame(
            [
                {
                    "msg": r.get("message", "")[:60],
                    "reason": r.get("_reason", "score_low"),
                    "title_f1": r.get("_scores", {}).get("title_f1"),
                    "time_f1": r.get("_scores", {}).get("time_f1"),
                    "loc_f1": r.get("_scores", {}).get("loc_f1"),
                    "scenario": r.get("scenario_id", ""),
                }
                for r in failed
            ]
        )
        st.dataframe(df_fail, use_container_width=True)
