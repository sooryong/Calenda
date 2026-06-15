"""c2 조립 — 3-way 재라벨 풀(_audited3.jsonl)에서 yes/pending/no 균형 선별.

- 오류(bool 라벨)·flag(음성→pending 추출필요) 제외.
- 날짜 누수 제외: 멀티턴 yes/pending인데 gold date가 절대(YYYY-MM-DD)이고 메시지에 명시 월/일 없음
  (= thread에서 절대날짜 누수, 요일→날짜 계산 유발). 명시 "6/19" 있는 건 유지.
- confidence·_label_reason·_audit_flag 제거. has_schedule=yes/pending/no 문자열.

사용:
    python scripts/build_c2_assemble.py            # dry-run
    python scripts/build_c2_assemble.py --apply    # train.jsonl 교체
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

POOL = Path("data/processed/_audited3.jsonl")
OUT = Path("data/processed/train.jsonl")
N_YES, N_NO = 350, 350   # pending은 가용분 전량

ABS = re.compile(r"^\d{4}-\d{2}-\d{2}")
EXPLICIT = re.compile(r"\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*월\s*\d{1,2}")


def is_leak(r) -> bool:
    """멀티턴 + gold 절대날짜 + 메시지에 명시 월/일 없음 = 누수."""
    if not r.get("thread_context"):
        return False
    txt = r.get("message", "") + " ".join(t.get("message", "") for t in r["thread_context"])
    if EXPLICIT.search(txt):
        return False
    return any(ABS.match(str(e.get("date") or "")) for e in r["gold"].get("events", []))


def clean(r):
    r = dict(r)
    r.pop("_label_reason", None); r.pop("_audit_flag", None)
    g = r.get("gold", {})
    g["events"] = [{k: v for k, v in e.items() if k != "confidence"} for e in g.get("events", [])]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(l) for l in POOL.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if not r.get("_audit_flag")]                      # flag 제외
    rows = [r for r in rows if r.get("gold", {}).get("has_schedule") in ("yes", "pending", "no")]  # 오류 제외

    yes = [r for r in rows if r["gold"]["has_schedule"] == "yes" and not is_leak(r)]
    pend = [r for r in rows if r["gold"]["has_schedule"] == "pending" and not is_leak(r)]
    no = [r for r in rows if r["gold"]["has_schedule"] == "no"]
    leak = sum(1 for r in rows if r["gold"]["has_schedule"] in ("yes", "pending") and is_leak(r))

    sel = [clean(r) for r in (yes[:N_YES] + pend + no[:N_NO])]

    from collections import Counter
    d = Counter(r["gold"]["has_schedule"] for r in sel)
    bad = 0
    for r in sel:
        for e in r["gold"].get("events", []):
            if e.get("date") and resolve_when(r["received_at"], e.get("date"), e.get("time"),
                                              e.get("end_time"), e.get("all_day", False))["start"] is None:
                bad += 1
    print(f"풀: yes {len(yes)} · pending {len(pend)} · no {len(no)} (날짜누수 제외 {leak})")
    print(f"선별 {len(sel)}: yes {d['yes']} · pending {d['pending']} · no {d['no']}")
    print(f"  detected(yes+pending) {d['yes']+d['pending']} · no {d['no']} = {d['no']/len(sel)*100:.0f}% no")
    print(f"  resolve 실패 {bad}")
    if not args.apply:
        print("dry-run (적용하려면 --apply)")
        return
    if bad:
        print("⚠ resolve 실패 — 미적용"); return
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sel) + "\n", encoding="utf-8")
    print(f"✓ {OUT} 교체 ({len(sel)}건)")


if __name__ == "__main__":
    main()
