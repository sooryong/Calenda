"""기존 gold(절대 start/end ISO) → 새 스키마(date 토큰 + time 객체 + 활동 title + organizer) 재라벨.

핵심: 메시지에서 상대표현·시각표현을 파싱해 토큰화하되, **resolver로 되돌렸을 때(round-trip)
원래 절대시각과 일치하는 토큰만 채택**한다. 일치하는 토큰이 없으면 절대값(YYYY-MM-DD / 안전 time)으로
폴백 → round-trip 실패 0 보장. (correctness는 폴백이 보장, 토큰 coverage는 best-effort)

사용: python scripts/relabel_schema.py            # *_new.jsonl 로 출력 + 통계 (덮어쓰기 안 함)
      python scripts/relabel_schema.py --apply    # 원본 덮어쓰기
"""
from __future__ import annotations
import argparse, json, re, sys
from datetime import datetime
sys.path.insert(0, "scripts")
from _common import resolve_date, resolve_time, resolve_when

WD = "월화수목금토일"


def parse_date_token(text, received_date, target_date):
    """메시지에서 date 토큰 추정. target_date로 round-trip 검증된 것만 채택, 아니면 절대/None."""
    c = []
    for w in ("글피", "모레", "내일", "오늘"):
        if w in text:
            c.append(w)
    for m in re.finditer(r"(\d+)\s*일\s*(뒤|후|있다가|지나)", text):
        c.append(f"{int(m.group(1))}일후")
    for m in re.finditer(r"(다다음|다음|이번)\s*주\s*([월화수목금토일])요일", text):
        c.append({"이번": "이번주", "다음": "다음주", "다다음": "다다음주"}[m.group(1)] + m.group(2))
    if re.search(r"다음\s*주(?!\s*[월화수목금토일]요일)", text):
        c.append("1주후")
    for m in re.finditer(r"(\d+)\s*주(?:일)?\s*(뒤|후)", text):
        c.append(f"{int(m.group(1))}주후")
    for m in re.finditer(r"(\d+)\s*개월\s*(뒤|후)", text):
        c.append(f"{int(m.group(1))}개월후")
    if re.search(r"한\s*달\s*(뒤|후)", text):
        c.append("1개월후")
    if re.search(r"다음\s*주말", text):
        c.append("다음주말")
    if re.search(r"이번\s*주말", text):
        c.append("이번주말")
    for tok in c:
        if resolve_date(received_date, tok) == target_date:
            return tok, "token"
    if target_date == received_date:        # 날짜표현 없고 당일 → date null (규칙7)
        return None, "today_null"
    return target_date.isoformat(), "absolute"


_MK = "(오전|오후|저녁|밤|낮|새벽|아침)"
_TIME_RE = re.compile(_MK + r"?\s*(\d{1,2})\s*시(\s*반|\s*\d{1,2}\s*분)?")
_HM_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _cands_from_text(text):
    out = []
    if "정오" in text:
        out.append({"hour": 12, "minute": 0, "marker": "정오"})
    if "자정" in text:
        out.append({"hour": 0, "minute": 0, "marker": "자정"})
    for m in _HM_RE.finditer(text):
        out.append({"hour": int(m.group(1)), "minute": int(m.group(2)), "marker": None})
    for m in _TIME_RE.finditer(text):
        mk, hh, frac = m.group(1), int(m.group(2)), m.group(3)
        minute = 30 if frac and "반" in frac else (int(re.sub(r"\D", "", frac)) if frac else 0)
        out.append({"hour": hh, "minute": minute, "marker": mk})
    return out


def _fallback_time(H, M):
    if H == 0:
        return {"hour": 0, "minute": M, "marker": None}
    if 1 <= H <= 11:
        return {"hour": H, "minute": M, "marker": "오전"}
    if H == 12:
        return {"hour": 12, "minute": M, "marker": "낮"}
    return {"hour": H, "minute": M, "marker": None}      # 13~23: 24h 그대로


def parse_time_obj(text, received_dt, target_hms):
    """메시지에서 time 객체 추정. resolve_time이 target과 일치하는 표면형만, 아니면 안전 폴백."""
    if target_hms is None:
        return None, "none"
    H, M = target_hms
    want = f"{H:02d}:{M:02d}"
    for cand in _cands_from_text(text):
        if resolve_time(cand, received_dt) == want:
            return cand, "surface"
    return _fallback_time(H, M), "fallback"


def _base_title(old_title):
    """옛 조합형 제목 → 활동 베이스. 'A와 약속, 장소: 발신자' → 'A와 약속'. compose_title의
    'not in title' 가드 덕에 누구/발신자 중복은 자동 회피되므로 앞 세그먼트만 취해도 안전."""
    if not old_title:
        return "일정"
    return old_title.split(",")[0].split(": ")[0].strip() or old_title.strip()


def _local(iso):
    """ISO에서 tz 무시한 (날짜, 'HH:MM'). 표기된 로컬 시계 기준."""
    if not iso:
        return None
    if "T" not in iso:                       # all_day date-only
        return (iso, None)
    d = datetime.fromisoformat(iso)
    return (d.date().isoformat(), f"{d.hour:02d}:{d.minute:02d}")


def relabel_event(rec, ev):
    recv_dt = datetime.fromisoformat(rec["received_at"])
    text = " ".join(t.get("message", "") for t in rec.get("thread_context", [])) + " " + rec["message"]
    stats = {}
    # date — 시작의 로컬 날짜(표기 기준) 사용
    sd = datetime.fromisoformat(ev["start"]).date() if ev.get("start") else None
    if sd is None:
        date_tok, stats["date"] = None, "no_start"
    else:
        date_tok, stats["date"] = parse_date_token(text, recv_dt.date(), sd)

    def hms(iso):
        d = datetime.fromisoformat(iso)
        return (d.hour, d.minute)

    time_obj, stats["time"] = parse_time_obj(text, recv_dt, hms(ev["start"]) if ev.get("start") else None)
    # 종료: 같은 로컬 날짜일 때만. cross-date/다른tz(익일 도착, 호텔 체크아웃)면 end=null (v1 단순화)
    end_obj, stats["end"] = None, "none"
    if ev.get("end"):
        end_dt = datetime.fromisoformat(ev["end"])
        if end_dt.date() == sd:
            end_obj, stats["end"] = parse_time_obj(text, recv_dt, (end_dt.hour, end_dt.minute))
        else:
            stats["end"] = "dropped_crossdate"
    new = {
        "title": _base_title(ev.get("title")),
        "date": date_tok,
        "time": time_obj,
        "end_time": end_obj,
        "all_day": ev.get("all_day", False),
        "location": ev.get("location"),
        "attendees": ev.get("attendees", []),
        "organizer": ev.get("organizer"),
        "description": ev.get("description"),
        "recurrence": ev.get("recurrence"),
        "confidence": ev.get("confidence"),
    }
    # round-trip 검증 (로컬 날짜+HH:MM 기준; tz·cross-date는 v1 정책상 무시)
    w = resolve_when(rec["received_at"], date_tok, time_obj, end_obj, new["all_day"])
    if new["all_day"]:                       # 종일은 날짜만 비교 (옛 인코딩 T00:00 무시)
        ls, lo = _local(w["start"]), _local(ev.get("start"))
        ok_start = bool(ls and lo and ls[0] == lo[0])
    else:
        ok_start = _local(w["start"]) == _local(ev.get("start"))
    # end는 드롭됐으면(end_obj None) 통과, 유지했으면 로컬 일치해야 함
    ok_end = (end_obj is None) or (_local(w["end"]) == _local(ev.get("end")))
    return new, stats, (ok_start and ok_end), (_local(w["start"]), _local(ev.get("start")), stats)


def process(path, out, apply):
    from collections import Counter
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    dstat, tstat, fails = Counter(), Counter(), []
    n_ev = 0
    for rec in rows:
        for i, ev in enumerate(rec["gold"].get("events", [])):
            n_ev += 1
            new, st, ok, dbg = relabel_event(rec, ev)
            dstat[st["date"]] += 1
            tstat[st["time"]] += 1
            rec["gold"]["events"][i] = new
            if not ok:
                fails.append((rec["scenario_id"], dbg))
    target = path if apply else out
    with open(target, "w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\n[{path}] events={n_ev}  -> {target}")
    print("  date:", dict(dstat))
    print("  time:", dict(tstat))
    print(f"  round-trip 실패: {len(fails)}")
    for sid, dbg in fails[:8]:
        print("   ", sid, dbg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    process("data/processed/train.jsonl", "data/processed/train_new.jsonl", args.apply)
    process("data/eval/golden.jsonl", "data/eval/golden_new.jsonl", args.apply)


if __name__ == "__main__":
    main()
