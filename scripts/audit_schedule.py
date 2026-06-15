"""기존 데이터 has_schedule 재감사 (Haiku) — 새 단일 기준(schedule_criterion.md)으로 양/음 재판정.

옛 가이드(날짜+시간=일정)로 라벨된 train.jsonl에는 통보성 양성 오라벨(택배 배송·결제 예정 등)이
섞여 있다. 이 스크립트는 각 페어를 criterion 기준으로 Haiku가 fresh 재판정하고:
  - has_schedule 불일치(특히 양성→음성)를 flag/교정
  - 모든 페어에 _label_reason 부여(감사·일관성)
title/date/time 등 추출값은 건드리지 않는다(양성으로 유지되면 그대로). 양성→음성이면 events=[].

사용:
    python scripts/audit_schedule.py                       # train.jsonl dry-run(통계+샘플)
    python scripts/audit_schedule.py --limit 50            # 50건 시험
    python scripts/audit_schedule.py --apply --out data/processed/_audited.jsonl   # 교정본 저장
    python scripts/audit_schedule.py --in data/eval/golden.jsonl --apply --out ...
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import call_claude, extract_json_block, build_user_block

CRITERION = Path("prompts/schedule_criterion.md").read_text(encoding="utf-8")

SYSTEM = """너는 '일정 양성/음성 판정자'다. 아래 [기준]을 **유일한 절대 기준**으로, 주어진 메시지가
캘린더에 등록할 일정인지(has_schedule)를 판정한다. 판정은 메시지 내용으로 fresh하게 — 기존 라벨 추측 금지.

반드시 JSON 하나만 출력: {"has_schedule": true 또는 false, "reason": "기준의 어느 항목에 해당하는지 한 줄"}

핵심: **날짜·시각이 있다고 일정이 아니다.** 거래·결제·적립·승인·배송 통보, 영업연락, 광고, 인사말은 음성.
사용자가 그 시각에 직접 참석·수행할 약속만 양성.

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
        return bool(obj.get("has_schedule")), (obj.get("reason") or "").strip()
    except Exception as e:
        return None, f"ERR:{e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/processed/train.jsonl")
    ap.add_argument("--out", default="data/processed/_audited.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.inp).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    print(f"{args.inp}: {len(rows)}건 재감사 (workers={args.workers})")

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(rows)}")

    pos2neg, neg2pos, err, agree = [], [], 0, 0
    for i, r in enumerate(rows):
        new_has, reason = results[i]
        old_has = bool(r.get("gold", {}).get("has_schedule"))
        if new_has is None:
            err += 1
            continue
        r["_label_reason"] = reason
        if new_has == old_has:
            agree += 1
        elif old_has and not new_has:          # 양성→음성 (통보 오라벨 교정)
            pos2neg.append(i)
            if args.apply:
                r["gold"] = {"has_schedule": False, "events": []}
        else:                                   # 음성→양성 (events 없으니 flag만, 수동/생성 검토)
            neg2pos.append(i)
            r["_audit_flag"] = "neg->pos(needs events)"

    print(f"\n동의 {agree} · 양성→음성 {len(pos2neg)} · 음성→양성 {len(neg2pos)} · 오류 {err}")
    print("── 양성→음성 교정 샘플(통보 오라벨) ──")
    for i in pos2neg[:18]:
        print(f"  [{rows[i].get('sender','')[:16]:16}] {rows[i].get('message','')[:50]!r}")
        print(f"      → {rows[i].get('_label_reason','')[:70]}")
    if neg2pos:
        print("── 음성→양성 flag(검토 필요, 자동교정 안 함) ──")
        for i in neg2pos[:8]:
            print(f"  [{rows[i].get('sender','')[:16]:16}] {rows[i].get('message','')[:50]!r} → {rows[i].get('_label_reason','')[:50]}")

    if args.apply:
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        print(f"\n✓ {args.out} 저장 (양성→음성 {len(pos2neg)}건 교정, 음성→양성 {len(neg2pos)}건 flag)")
    else:
        print("\ndry-run (적용하려면 --apply --out ...)")


if __name__ == "__main__":
    main()
