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
import re
from pathlib import Path

# kind: 'keep'(항상 보존) | 'pool'(캡 맞추려 제거 가능).  real: 실데이터 여부(표시용).
SOURCES = [
    {"path": "data/processed/base_r16.jsonl",         "kind": "pool", "real": False},  # 안정 base = r16 train.jsonl(git 72e7b15, 0.827). pool=train.jsonl 자기참조 잠식 회피.
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
    # r17_hardcases 제외: 과트리거 음성이 r16 대비 회귀시킴. r18은 r16 + N일 종일 양성만.
    {"path": "data/processed/r18_hardcases.jsonl",     "kind": "keep", "real": False},  # r18: 단독 N일 종일(time=null) 양성만(회귀 없이 공백만 닫기)
    {"path": "data/processed/r19_hardcases.jsonl",     "kind": "keep", "real": False},  # r19: informal 모임 제목충실 + 번호목록 누적 멀티턴(단일일정·참석자union) + 모임테마 음성 (할루시네이션 교정)
    {"path": "data/processed/r20_hardcases.jsonl",     "kind": "keep", "real": False},  # r20: 가맹점-장소형 거래알림 음성(출금 FP) + 격식 기관메일 선택참석 양성(Gmail FN) + 격식메일 음성 (실사용 2대 실패 교정)
    {"path": "data/processed/r21_hardcases.jsonl",     "kind": "keep", "real": False},  # r21: 격식 기관메일 음성 72(공고·회람·지난행사·일정확인·추후안내·정산·뉴스) — G2 confident FP 상쇄 (r20 과발화 분석)
    {"path": "data/processed/r22_hardcases.jsonl",     "kind": "keep", "real": False},  # r22: 잔존 confident FP 강화(자료공유·회람·일정확인 ~25/형) + 재난경보 음성 12 (r21 specificity 불변 분석)
    {"path": "data/processed/r23_hardcases.jsonl",     "kind": "keep", "real": False},  # r23: 멀티턴 '상대가 맨 「네」로 확정, 값은 내 이전 메시지'(신스키마 date토큰) + 거절/로지스틱스 음성 (박상로 카톡 실패: 다음주화/6-29 환각)
    # 다음 라운드: feedback_export 를 여기에 'keep'으로 추가 (scripts/ingest_feedback.py)

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


# 모델이 그대로 외워 description으로 뱉는 합성 보일러플레이트(메시지 근거 없음 → 환각).
# base_r16/thread_confirm/cowork 전반에 박혀 있어(295건) gold에서 null화한다. 시간/날짜 불가침.
_BOILERPLATE_DESC = ("스레드 협의 확정",)


def normalize_gold(r: dict) -> dict:
    """저품질 보일러플레이트 description 제거 — 모든 소스 일괄(소스 파일 비파괴)."""
    for ev in (r.get("gold", {}).get("events") or []):
        if isinstance(ev, dict):
            d = ev.get("description")
            if isinstance(d, str) and any(b in d for b in _BOILERPLATE_DESC):
                ev["description"] = None
    return r


_GROUND_FIELDS = ("title", "location", "organizer")


def grounding(r: dict) -> float:
    """양성 gold의 추출 필드(title/location/organizer/attendees)가 message에 근거하는 비율.
    낮을수록 '부적합' — 메시지에 없는 내용을 정답이라 학습 → 환각 연료. 캡 컷 우선순위에 사용.
    음성·근거판정 불가(필드 없음)는 1.0(안 자름). 날짜/시각 토큰은 표면형 변환되므로 제외."""
    g = r.get("gold", {})
    if not g.get("has_schedule"):
        return 1.0
    msg = r.get("message", "") or ""
    for t in (r.get("thread_context") or []):     # 멀티턴: 근거는 직전 메시지에 있을 수 있음
        msg += " " + (t.get("message", "") or "")
    msg_l = msg.lower()
    checked = hit = 0
    for ev in g.get("events", []):
        for f in _GROUND_FIELDS:
            v = ev.get(f)
            if isinstance(v, str) and v.strip():
                checked += 1
                toks = [w for w in re.split(r"[\s,·/]+", v) if len(w) >= 2]
                if v.lower() in msg_l or any(w.lower() in msg_l for w in toks):
                    hit += 1
        for a in (ev.get("attendees") or []):
            if isinstance(a, str) and a.strip():
                checked += 1
                if a.lower() in msg_l:
                    hit += 1
    return hit / checked if checked else 1.0


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
    ap.add_argument("--cap", type=int, default=2100)  # r18: base_r16(2000) 전량 보존 + N일 양성 추가(잠식 방지)
    ap.add_argument("--neg", type=float, default=0.40, help="목표 음성 비율")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/processed/train_assembled.jsonl")
    ap.add_argument("--apply", action="store_true", help="train.jsonl 실제 갱신")
    ap.add_argument("--anonymize", action="store_true",
                    help="출력 직전 PII 익명화(실 사적 메시지 push 전). 시간/날짜 토큰은 불가침.")
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
    # base 합성 양성: grounding 내림차순 정렬 → 잘 근거된 것 우선 보존, 부적합(환각 연료)부터 컷.
    # 앞선 shuffle이 동점 grounding의 결정적 tie-break(seed 고정). 음성은 정렬 안 함(전량 활용).
    pool_pos.sort(key=grounding, reverse=True)

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
    final = [normalize_gold(r) for r in final]   # 보일러플레이트 description null화(일괄)

    # 3) 리포트
    print("=== 입력 ===")
    print(f"  keep(보존) {len(keep)}  /  pool(합성·제거가능) {len(pool)}  /  실데이터 {len(real_keys)}")
    print(f"=== 출력(캡 {cap}, 목표음성 {args.neg:.0%}) — {len(final)}건 ===")
    print(breakdown(final))
    evicted = len(keep) + len(pool) - len(final)
    print(f"  제거된 합성: {max(0, evicted)}건 (keep·실데이터·엣지는 보존)")
    dropped_pos = pool_pos[need_pos:]
    if take_pos or dropped_pos:
        avg = lambda xs: sum(xs) / len(xs) if xs else 1.0
        print(f"  grounding 컷: 보존 base양성 {len(take_pos)}건 평균 {avg([grounding(r) for r in take_pos]):.2f}"
              f" / 제거 {len(dropped_pos)}건 평균 {avg([grounding(r) for r in dropped_pos]):.2f}"
              f" (낮을수록 환각 연료 — 부적합부터 컷)")

    # 4) (옵션) 익명화 — dedup·균형은 raw로 끝낸 뒤 출력 직전에만 적용
    if args.anonymize:
        from anonymize import anonymize_record
        final = [anonymize_record(r) for r in final]
        anon_n = sum(1 for r in final if r.get("_anon"))
        print(f"  익명화 적용: {anon_n}건 (전화·주민·카드·계좌·이메일·URL 마스킹 + 이름 일관 가명; 날짜/시각 불가침)")

    out = "data/processed/train.jsonl" if args.apply else args.out
    with open(out, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {out} {'(train.jsonl 갱신됨)' if args.apply else '(미리보기 — --apply로 적용)'}")


if __name__ == "__main__":
    main()
