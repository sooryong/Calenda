"""schedule_status 3-way 재라벨 (Haiku) — schedule_criterion.md 기준으로 yes/pending/no 분류.

3-분류: yes(확정 일정)·pending(공고·안내·초대·미확정 제안 = 미래 가능성)·no(거래·통보·광고).
confidence 필드는 폐지 → events에서 제거.

처리:
  - no  → gold {schedule_status:"no", events:[]}
  - yes/pending → 기존 events 유지(confidence만 제거), schedule_status을 3-way 값으로.
  - (드물게) 음성이었는데 yes/pending 판정 + events 없음 → flag(추출 필요, 수동/생성).

사용:
    python scripts/audit_schedule.py --in data/processed/train.jsonl.pre_c1bak --apply --out data/processed/_audited3.jsonl
    python scripts/audit_schedule.py --in data/eval/golden.jsonl --apply --out data/eval/golden.jsonl
    python scripts/audit_schedule.py --limit 40            # dry-run 시험
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import call_claude, extract_json_block, build_user_block

CRITERION = Path("prompts/schedule_criterion.md").read_text(encoding="utf-8")

SYSTEM = """너는 '일정 분류기'다. 아래 [기준]을 **유일한 절대 기준**으로, 주어진 메시지의 schedule_status을
**yes / pending / no** 셋 중 하나로 분류한다. 메시지 내용으로 fresh하게 판단(기존 라벨 추측 금지).

반드시 JSON 하나만 출력: {"schedule_status": "yes" 또는 "pending" 또는 "no", "reason": "어느 기준 항목인지 한 줄"}

요약:
- yes  = 사용자가 당사자로 확실히 참석/수행할 **확정 일정**(회의·예약·면접·확정 약속).
- pending = **미래 행사/행동 가능성**(공고·모집·마감·설명회·포럼·세미나·교육·출범식·초대·미확정 제안) — 확정 아님, 사용자 판단.
- no   = 비-일정(거래·결제·적립·배송·인증·청구·광고·인사·과거회고·남의일정). **날짜·시각 있어도 거래/통보면 no.**
★ 거래 "안내"(적립·결제·배송)는 no, 행사/모집 "안내"는 pending을 구분하라.

[기준]
""" + CRITERION


def judge(rec: dict):
    try:
        ub = build_user_block({
            "channel": rec.get("channel", ""), "received_at": rec.get("received_at", ""),
            "sender": rec.get("sender", ""), "message": rec.get("message", ""),
            "thread_context": rec.get("thread_context"),
        })
        raw = call_claude(SYSTEM, ub, temperature=0.0, max_tokens=200)
        obj = json.loads(extract_json_block(raw))
        label = (obj.get("schedule_status") or "").strip().lower()
        if label not in ("yes", "pending", "no"):
            return None, f"BAD:{label}"
        return label, (obj.get("reason") or "").strip()
    except Exception as e:
        return None, f"ERR:{e}"


def strip_conf(ev: dict) -> dict:
    ev.pop("confidence", None)
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/processed/train.jsonl")
    ap.add_argument("--out", default="data/processed/_audited3.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.inp).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    print(f"{args.inp}: {len(rows)}건 3-way 재라벨 (workers={args.workers})")

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(rows)}")

    from collections import Counter
    dist = Counter()
    promoted_flag, err = [], 0
    for i, r in enumerate(rows):
        label, reason = results[i]
        if label is None:
            err += 1
            continue
        r["_label_reason"] = reason
        g = r.setdefault("gold", {})
        # 기존 schedule_status(bool 또는 str) → events 유무
        had_events = bool(g.get("events"))
        old_pos = g.get("schedule_status") in (True, "yes", "pending")
        if label == "no":
            if args.apply:
                g["schedule_status"] = "no"; g["events"] = []
        else:  # yes / pending
            if had_events:
                if args.apply:
                    g["schedule_status"] = label
                    g["events"] = [strip_conf(e) for e in g.get("events", [])]
            elif not old_pos:
                # 음성이었는데 yes/pending — events 없음 → flag
                promoted_flag.append(i)
                r["_audit_flag"] = f"{label}(needs events)"
                if args.apply:
                    g["schedule_status"] = "no"; g["events"] = []  # 보수적 유지
            else:
                if args.apply:
                    g["schedule_status"] = label
        # confidence 제거(no여도)
        if args.apply:
            g["events"] = [strip_conf(e) for e in g.get("events", [])]
        dist[label] += 1

    print(f"\n3-way 분포: yes {dist['yes']} · pending {dist['pending']} · no {dist['no']} · 오류 {err}")
    print(f"음성→yes/pending flag(추출 필요, 보수적 no 유지): {len(promoted_flag)}건")
    for i in promoted_flag[:8]:
        print(f"  [{results[i][0]}] {rows[i].get('message','')[:50]!r} → {rows[i].get('_label_reason','')[:50]}")

    if args.apply:
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        print(f"\n✓ {args.out} 저장")
    else:
        print("\ndry-run (적용하려면 --apply --out ...)")


if __name__ == "__main__":
    main()
