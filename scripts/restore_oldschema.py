"""구스키마(start/end 절대시각) 행 → 신스키마(date 토큰 + time{marker}) 변환.

라운드트립 게이트: 메시지에서 뽑은 (date 토큰, time)을 resolve_when으로 풀어
저장된 절대 start/end와 정확히 일치할 때만 채택 → 변환 정확성을 기계적으로 보장.
표시어가 없으면 marker=None(충실)으로만 시도하고, 안 맞으면 제외(추측 학습 회피).

사용: python scripts/restore_oldschema.py   (e790970에서 311행 읽어 변환 리포트)
"""
from __future__ import annotations
import sys, json, re, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

MARK_WORDS = ["새벽", "아침", "오전", "정오", "낮", "오후", "저녁", "밤", "자정"]


def parse_date(msg: str):
    for tok in ["오늘", "내일", "모레", "글피"]:
        if tok in msg:
            return tok
    m = re.search(r"(이번주말|다음주말|이번\s?주말|다음\s?주말)", msg)
    if m:
        return m.group(1).replace(" ", "")
    m = re.search(r"(이번주|다음주|다다음주)\s?([월화수목금토일])요일?", msg)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.search(r"(\d+)\s?일\s?후", msg)
    if m:
        return f"{m.group(1)}일후"
    m = re.search(r"(\d+)\s?주\s?후", msg)
    if m:
        return f"{m.group(1)}주후"
    m = re.search(r"(\d+)\s?개월\s?후", msg)
    if m:
        return f"{m.group(1)}개월후"
    m = re.search(r"(\d{1,2})\s?월\s?(\d{1,2})\s?일", msg)
    if m:
        return f"{int(m.group(1))}월{int(m.group(2))}일"
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", msg)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    m = re.search(r"([월화수목금토일])요일", msg)
    if m:
        return f"{m.group(1)}요일"
    m = re.search(r"(?<!\d)(\d{1,2})\s?일(?!후|간|짜|째)", msg)
    if m:
        return f"{int(m.group(1))}일"
    return None


def parse_time(msg: str):
    mk = next((w for w in MARK_WORDS if w in msg), None)
    m = re.search(r"(\d{1,2})\s?시\s?(\d{1,2})?\s?(분|반)?", msg)
    if m:
        h = int(m.group(1))
        mn = 30 if m.group(3) == "반" else (int(m.group(2)) if m.group(2) else 0)
        return (h, mn, mk)
    m = re.search(r"(\d{1,2}):(\d{2})", msg)
    if m:
        return (int(m.group(1)), int(m.group(2)), mk)
    return None


def derive_time(h: int, m: int):
    if h == 0:
        return {"hour": 12, "minute": m, "marker": "자정"}
    if h < 12:
        return {"hour": h, "minute": m, "marker": "오전"}
    if h == 12:
        return {"hour": 12, "minute": m, "marker": "정오"}
    return {"hour": h, "minute": m, "marker": None}


def build(ev, dtok, time_obj, end_obj, all_day):
    return {"title": ev.get("title"), "date": dtok, "time": time_obj, "end_time": end_obj,
            "all_day": all_day, "location": ev.get("location"), "attendees": ev.get("attendees", []),
            "organizer": ev.get("organizer"), "description": ev.get("description"),
            "recurrence": ev.get("recurrence"), "confidence": ev.get("confidence", 0.85)}


def convert(row):
    """성공 시 신스키마 row, 실패 시 None."""
    msg = row.get("message", ""); recv = row.get("received_at")
    evs = row.get("gold", {}).get("events", [])
    if len(evs) != 1:
        return None, "multi_event"
    ev = evs[0]
    start, end, all_day = ev.get("start"), ev.get("end"), bool(ev.get("all_day"))
    dtok = parse_date(msg)
    if not dtok:
        return None, "no_date_token"
    # 종일/시각없음
    if all_day or not start or "T" not in start:
        r = resolve_when(recv, dtok, None, None, True)
        if r["start"] and start and r["start"][:10] == start[:10]:
            new = dict(row); new["gold"] = {"has_schedule": True, "events": [build(ev, dtok, None, None, True)]}
            return new, "ok_allday"
        return None, "date_mismatch"
    pt = parse_time(msg)
    if not pt:
        return None, "no_time"
    h, mn, mk = pt
    end_obj = None
    if end and "T" in end:
        end_obj = derive_time(int(end[11:13]), int(end[14:16]))
    cands = [mk] if mk else [None]          # 표시어 있으면 그것만, 없으면 None(충실)만
    for cm in cands:
        cand = {"hour": h, "minute": mn, "marker": cm}
        r = resolve_when(recv, dtok, cand, end_obj, False)
        if r["start"] == start and (not end or r["end"] == end):
            new = dict(row); new["gold"] = {"has_schedule": True, "events": [build(ev, dtok, cand, end_obj, False)]}
            return new, "ok"
    return None, "roundtrip_fail"


def load_old():
    raw = subprocess.run(["git", "show", "e790970:data/processed/train.jsonl"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    return [r for r in rows if any("start" in ev for ev in r.get("gold", {}).get("events", []) or [])]


def main():
    import collections, re as _re
    old = load_old()
    passed = []; reasons = collections.Counter(); by_pref = collections.Counter()
    for r in old:
        new, why = convert(r)
        reasons[why] += 1
        if new:
            passed.append(new)
            by_pref[_re.sub(r'\d+$', '', r.get("scenario_id", "")).rstrip('_')] += 1
    Path("data/processed/_restored.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in passed) + "\n", encoding="utf-8")
    print(f"구스키마 {len(old)}행 → 변환 성공 {len(passed)}행 ({len(passed)/len(old):.0%})")
    print("사유:", dict(reasons))
    print("성공 접두:", dict(by_pref))
    n_loc = sum(1 for r in passed if r["gold"]["events"][0].get("location"))
    n_thr = sum(1 for r in passed if r.get("thread_context"))
    print(f"성공 중 location 보유: {n_loc} · thread_context 보유: {n_thr}")
    print("→ data/processed/_restored.jsonl")


if __name__ == "__main__":
    main()
