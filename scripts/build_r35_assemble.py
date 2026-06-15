"""r35 1000셋 조립 — 재감사 풀(재사용) + 생성 멀티턴 음성.

구성: A 단일 600(양300/음300) + B 멀티 400(양183~200/음 나머지) = 1000, 음성 ~50%.
음성은 날짜·시각 보유율을 높여 'date/time=일정' 지름길 차단.
audit 메타(_label_reason/_audit_flag/_qa)는 학습본에서 제거.

사용:
    python scripts/build_r35_assemble.py            # dry-run(구성·균형 리포트)
    python scripts/build_r35_assemble.py --apply    # data/processed/train.jsonl 교체
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import resolve_when

POOL = Path("data/processed/_audited.jsonl")
GEN = Path("data/processed/_r35_mtneg_checked.jsonl")
OUT = Path("data/processed/train.jsonl")

# 목표
A_POS, A_NEG = 300, 300        # 단일
B_POS_MAX, B_TOTAL = 200, 400  # 멀티 (양성은 보유분까지, 나머지 음성)

DT = re.compile(r"(오전|오후|저녁|정오|자정|새벽|아침)|\d{1,2}\s*시|\d{1,2}:\d{2}|"
                r"\d{1,2}\s*월\s*\d{1,2}|\d{1,2}/\d{1,2}|적립|결제|승인|출금|청구|배송|인증|예정")


def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def strip_meta(r):
    for k in ("_label_reason", "_audit_flag", "_qa"):
        r.pop(k, None)
    return r


def has_dt(r):
    t = r.get("message", "") + " ".join(x.get("message", "") for x in (r.get("thread_context") or []))
    return bool(DT.search(t))


def mt(r):
    return bool(r.get("thread_context"))


def take(seq, n):
    """결정론적 선별(앞에서 n개). 입력 순서가 시나리오 혼합이라 다양."""
    return seq[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pool = [r for r in load(POOL) if not r.get("_audit_flag")]
    gen = load(GEN) if GEN.exists() else []
    # 생성분 중 이중검증 통과(음성 유지)만
    gen = [r for r in gen if not r["gold"]["has_schedule"]]

    s_pos = [r for r in pool if r["gold"]["has_schedule"] and not mt(r)]
    s_neg = [r for r in pool if not r["gold"]["has_schedule"] and not mt(r)]
    m_pos = [r for r in pool if r["gold"]["has_schedule"] and mt(r)]
    m_neg_pool = [r for r in pool if not r["gold"]["has_schedule"] and mt(r)]

    # 단일 음성: 날짜·시각 보유분 우선(지름길 차단) + 나머지로 채움
    s_neg_dt = [r for r in s_neg if has_dt(r)]
    s_neg_other = [r for r in s_neg if not has_dt(r)]
    sel_s_neg = take(s_neg_dt, int(A_NEG * 0.7)) + take(s_neg_other, A_NEG - int(A_NEG * 0.7))
    sel_s_neg = sel_s_neg[:A_NEG]

    sel_s_pos = take(s_pos, A_POS)

    # 멀티 양성: 보유분(<=200)
    sel_m_pos = take(m_pos, B_POS_MAX)
    b_neg_target = B_TOTAL - len(sel_m_pos)
    # 멀티 음성: 기존 + 생성
    m_neg_all = m_neg_pool + gen
    sel_m_neg = take(m_neg_all, b_neg_target)

    final = [strip_meta(dict(r)) for r in (sel_s_pos + sel_s_neg + sel_m_pos + sel_m_neg)]

    pos = sum(1 for r in final if r["gold"]["has_schedule"])
    neg = len(final) - pos
    npos_dt = sum(1 for r in final if r["gold"]["has_schedule"] and has_dt(r))
    nneg_dt = sum(1 for r in final if not r["gold"]["has_schedule"] and has_dt(r))
    bad = 0
    for r in final:
        for e in r["gold"].get("events", []):
            if e.get("date") and resolve_when(r["received_at"], e.get("date"), e.get("time"),
                                              e.get("end_time"), e.get("all_day", False))["start"] is None:
                bad += 1

    print(f"조립 {len(final)}  (양성 {pos} · 음성 {neg} = {neg/len(final)*100:.1f}% neg)")
    print(f"  A 단일: 양성 {len(sel_s_pos)} · 음성 {len(sel_s_neg)}")
    print(f"  B 멀티: 양성 {len(sel_m_pos)} · 음성 {len(sel_m_neg)} (기존 {len(m_neg_pool)} + 생성 {len(sel_m_neg)-min(len(m_neg_pool),len(sel_m_neg))})")
    print(f"  ★날짜·시각 보유: 양성 {npos_dt}/{pos}={npos_dt/max(1,pos)*100:.0f}% · 음성 {nneg_dt}/{neg}={nneg_dt/max(1,neg)*100:.0f}%")
    # P(양성|날짜+시각) 근사
    both = npos_dt + nneg_dt
    print(f"  ★P(양성|날짜·시각) ≈ {npos_dt/max(1,both):.2f}  (목표 base rate {pos/len(final):.2f}에 근접할수록 지름길 약화)")
    print(f"  resolve 실패 {bad}")
    if not args.apply:
        print("\ndry-run (적용하려면 --apply)")
        return
    if bad:
        print("⚠ resolve 실패 — 미적용"); return
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in final) + "\n", encoding="utf-8")
    print(f"\n✓ {OUT} 교체 ({len(final)}건)")


if __name__ == "__main__":
    main()
