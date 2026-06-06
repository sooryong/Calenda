"""학습셋 조립기 — 캡(기본 2000) + 채널·음성 균형 + 실데이터/엣지케이스 보존.

설계(데이터셋이 라운드마다 무한히 늘지 않게):
  - 'keep' 소스(실데이터·엣지케이스 부스트)는 **항상 보존**.
  - 'pool' 소스(합성 base)는 **캡을 맞추기 위해 가치 낮은 것부터 제거**.
  - 최종 음성 비율을 목표치(기본 0.40) 근처로 맞춤 — over-trigger 방지([[feedback_boost_negative_balance]]).
  - age(나이)가 아니라 **kind(실/엣지/합성) 기준**으로 제거 → 토대 커버리지(주말·멀티턴·multi-event) 유지.

사용:
    python scripts/assemble_train.py                # 미리보기(train_assembled.jsonl) + 내역 출력
    python scripts/assemble_train.py --apply        # train.jsonl 실제 갱신
    python scripts/assemble_train.py --cap 2000 --neg 0.40 --seed 42

소스 목록(SOURCES)을 라운드마다 편집해 새 부스트/실데이터를 추가하면 된다.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# kind: 'keep'(항상 보존) | 'pool'(캡 맞추려 제거 가능).  real: 실데이터 여부(표시용).
SOURCES = [
    {"path": "data/processed/train.jsonl",            "kind": "pool", "real": False},  # 현 2245(합성 base+부스트)
    {"path": "data/processed/weekend_boost.jsonl",    "kind": "keep", "real": False},  # 엣지: 주말 횡단
    {"path": "data/processed/thread_confirm.jsonl",   "kind": "keep", "real": False},  # 엣지: 멀티턴 합의
    {"path": "data/processed/cowork_boost.jsonl",     "kind": "keep", "real": False},  # 엣지: 협업
    {"path": "data/processed/gmail_real_train.jsonl", "kind": "keep", "real": True},   # 실데이터: Gmail
    {"path": "data/processed/sms_real.jsonl",         "kind": "keep", "real": True},   # 실데이터: SMS(adb)
    {"path": "data/processed/kakao_real.jsonl",       "kind": "keep", "real": True},   # 실데이터: 카톡(캡처)
    {"path": "data/processed/ad_negative.jsonl",      "kind": "keep", "real": False},  # 하드네거티브: 광고/프로모션/알림톡(브랜드 발신, 날짜 박힘)
    {"path": "data/processed/r14_hardcases.jsonl",     "kind": "keep", "real": False},  # r14: gmail음성·광고보강·제3자·마감=종일(r13 실패분석)
    {"path": "data/processed/r15_hardcases.jsonl",     "kind": "keep", "real": False},  # r15: gmail업무음성·광고·제3자·재난경보·마감종일·환각억제·terse·멀티턴(r14 실패분석)
    {"path": "data/processed/r16_hardcases.jsonl",     "kind": "keep", "real": False},  # r16: precision 밀착음성 + time/date(N일·요일·date-only·경쟁날짜·멀티턴) (r15 디커플링 분석)
    # 다음 라운드: feedback_export 를 여기에 'keep'으로 추가

]


def load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"  ! 건너뜀(없음): {path}")
        return []
    rows = []
    with open(p, "rb") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def key(r: dict) -> str:
    """중복 판정 키: 채널+메시지+gold. 같은 입력·정답이면 동일."""
    return f"{r.get('channel','')}|{r.get('message','')}|{json.dumps(r.get('gold',{}), ensure_ascii=False, sort_keys=True)}"


def is_pos(r: dict) -> bool:
    return bool(r.get("gold", {}).get("has_schedule"))


def breakdown(rows: list[dict]) -> str:
    chans = {}
    for r in rows:
        c = r.get("channel", "other")
        d = chans.setdefault(c, [0, 0])
        d[0 if is_pos(r) else 1] += 1
    lines = [f"  {'채널':<8}{'일정':>6}{'음성':>6}{'계':>6}"]
    tot_p = tot_n = 0
    for c, (p, n) in sorted(chans.items()):
        lines.append(f"  {c:<8}{p:>6}{n:>6}{p + n:>6}")
        tot_p += p; tot_n += n
    total = tot_p + tot_n
    negr = tot_n / total if total else 0
    lines.append(f"  {'합계':<8}{tot_p:>6}{tot_n:>6}{total:>6}   (음성 {negr:.0%})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=2000)
    ap.add_argument("--neg", type=float, default=0.40, help="목표 음성 비율")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/processed/train_assembled.jsonl")
    ap.add_argument("--apply", action="store_true", help="train.jsonl 실제 갱신")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # 1) keep / pool 적재 + 중복 제거
    keep, keep_keys, real_keys = [], set(), set()
    for s in SOURCES:
        if s["kind"] != "keep":
            continue
        for r in load(s["path"]):
            k = key(r)
            if k in keep_keys:
                continue
            keep_keys.add(k)
            if s["real"]:
                real_keys.add(k)
            keep.append(r)

    pool, seen = [], set(keep_keys)
    for s in SOURCES:
        if s["kind"] != "pool":
            continue
        for r in load(s["path"]):
            k = key(r)
            if k in seen:           # keep에 이미 있거나 중복 → 제외
                continue
            seen.add(k)
            pool.append(r)

    # 2) 음성 균형 맞춰 pool에서 채우기
    cap = args.cap
    keep_pos = [r for r in keep if is_pos(r)]
    keep_neg = [r for r in keep if not is_pos(r)]
    pool_pos = [r for r in pool if is_pos(r)]
    pool_neg = [r for r in pool if not is_pos(r)]
    rng.shuffle(pool_pos); rng.shuffle(pool_neg)

    target_neg = round(cap * args.neg)
    target_pos = cap - target_neg
    need_neg = max(0, target_neg - len(keep_neg))
    need_pos = max(0, target_pos - len(keep_pos))

    take_neg = pool_neg[:need_neg]
    take_pos = pool_pos[:need_pos]
    final = keep + take_neg + take_pos

    # 부족하면(한쪽 풀 고갈) 남은 pool로 캡까지 채움
    if len(final) < cap:
        rest = pool_neg[need_neg:] + pool_pos[need_pos:]
        rng.shuffle(rest)
        final += rest[: cap - len(final)]
    # 넘치면(keep이 캡 초과 등) 합성부터 잘라냄
    if len(final) > cap:
        synth = [r for r in final if key(r) not in real_keys]
        rng.shuffle(synth)
        drop = set(id(r) for r in synth[: len(final) - cap])
        final = [r for r in final if id(r) not in drop]

    rng.shuffle(final)

    # 3) 리포트
    print("=== 입력 ===")
    print(f"  keep(보존) {len(keep)}  /  pool(합성·제거가능) {len(pool)}  /  실데이터 {len(real_keys)}")
    print(f"=== 출력(캡 {cap}, 목표음성 {args.neg:.0%}) — {len(final)}건 ===")
    print(breakdown(final))
    evicted = len(keep) + len(pool) - len(final)
    print(f"  제거된 합성: {max(0, evicted)}건 (keep·실데이터·엣지는 보존)")

    out = "data/processed/train.jsonl" if args.apply else args.out
    with open(out, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {out} {'(train.jsonl 갱신됨)' if args.apply else '(미리보기 — --apply로 적용)'}")


if __name__ == "__main__":
    main()
