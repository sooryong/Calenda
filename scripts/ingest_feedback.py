"""앱 피드백 export(JSONL) → 학습 페어(data/processed/feedback_<round>.jsonl) 변환기.

배경(경로: incremental learning):
  Android FeedbackExporter가 사용자 행동을 학습 페어로 내보낸다(설정 → 학습 데이터 보내기).
  스키마: {scenario_id, received_at, channel, sender, language, message, gold, _feedback, thread_context?}
    _feedback ∈ {ADDED, AUTO_ADDED, DISMISSED, EDITED}
    gold      = EDITED→사용자 교정본 / DISMISSED→{has_schedule:false} / ADDED→모델 추출(양성)

★ 유일한 변환 포인트 — EDITED 의 date 가 **절대일자(yyyy-MM-dd)**로 저장된다(EventEditActivity.kt):
  하지만 모델은 extract-resolve 설계상 **상대 토큰**(내일·다음주화·12일…)을 내야 한다. 절대일자로
  학습시키면 "내일"→날짜계산을 모델에 가르치는 꼴(0.5B가 못 하는 바로 그것). 그래서 여기서
  절대일자를 **_common.resolve_date 로 검증된 상대 토큰**으로 되돌린다.
    - 메시지에 표면형이 실제로 들어있는 토큰을 최우선(추출 가능한 정답).
    - 후보가 target 으로 재계산(resolve_date)될 때만 채택(미러 정합 보증).
    - 어떤 토큰도 일치 안 하면 절대일자 그대로 둠(스키마가 명시 절대일자는 허용) + 검토 플래그.
  DISMISSED/ADDED 의 gold 는 이미 토큰 스키마(또는 has_schedule:false)라 그대로 통과.

사용:
    # 폰에서 받은 export 들을 data/feedback_raw/ 에 모아두고:
    python scripts/ingest_feedback.py --round r19
    # 또는 명시 입력:
    python scripts/ingest_feedback.py --in data/feedback_raw/feedback_export.jsonl --round r19

출력:
    data/processed/feedback_<round>.jsonl   ← assemble_train.SOURCES 에 kind="keep", real=True 로 추가
    data/feedback_raw/<round>_review.jsonl  ← EDITED 중 메시지-표면 미일치(검토 권장)분
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from _common import resolve_date  # 단일 진실원 미러(역변환 검증에 사용)

_WD_KO = "월화수목금토일"
_ABS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _candidates(received_date: _date, target: _date) -> list[str]:
    """target 으로 갈 수 있는 상대 토큰 후보를 '자연스러운 순서'로. (검증은 호출측에서.)
    우선순위: 고정(내일류) > 일자(N일) > 요일 > 주말 > N주후 > N개월후 > N년후 > N일후(최후)."""
    offset = (target - received_date).days
    cands: list[str] = []
    fixed = {0: "오늘", 1: "내일", 2: "모레", 3: "글피"}
    if offset in fixed:
        cands.append(fixed[offset])
    cands.append(f"{target.day}일")                       # 단독 일자 (가까운 미래 N일)
    wd = _WD_KO[target.weekday()]
    for pre in ("이번주", "다음주", "다다음주"):
        cands.append(f"{pre}{wd}")
    cands += ["이번주말", "다음주말"]
    if offset >= 7 and offset % 7 == 0:
        cands.append(f"{offset // 7}주후")
    if offset >= 28:                                       # 월 단위(달 길이 편차는 검증이 걸러냄)
        base = round(offset / 30.0)
        for m in (base - 1, base, base + 1):
            if m >= 1:
                cands.append(f"{m}개월후")
    if offset >= 365:                                      # 년 단위
        base = round(offset / 365.0)
        for y in (base, base + 1):
            if y >= 1:
                cands.append(f"{y}년후")
    if offset >= 1:
        cands.append(f"{offset}일후")                      # 최후의 수단(큰 N일후는 부자연)
    # 중복 제거(순서 유지)
    seen, uniq = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq


def relativize_date(received_date: _date, date_val, message: str) -> tuple[object, str]:
    """절대일자(yyyy-MM-dd) → 검증된 상대 토큰. 반환 (값, method).
    method ∈ {passthrough, message-match, canonical, absolute-kept}."""
    if not isinstance(date_val, str) or not _ABS_RE.match(date_val):
        return date_val, "passthrough"                    # 이미 토큰/None/비절대 → 손대지 않음
    try:
        target = _date.fromisoformat(date_val)
    except ValueError:
        return date_val, "passthrough"
    verified = [c for c in _candidates(received_date, target)
                if resolve_date(received_date, c) == target]
    if not verified:
        return date_val, "absolute-kept"                  # 스키마 허용(명시 절대일자) + 검토
    msg = (message or "").replace(" ", "")
    in_msg = [c for c in verified if c.replace(" ", "") in msg]
    if in_msg:
        return in_msg[0], "message-match"                 # 메시지에 실제로 있는 표면형 = 추출 가능 정답
    return verified[0], "canonical"                       # 표면 미일치 → 가장 자연스러운 토큰(검토 권장)


def _recv_date(received_at: str) -> _date | None:
    try:
        return _datetime.fromisoformat(str(received_at)).date()
    except Exception:
        return None


def process_row(row: dict, stats: dict) -> tuple[dict | None, dict | None]:
    """한 페어 변환. 반환 (학습페어 | None, 검토행 | None)."""
    fb = row.get("_feedback", "")
    gold = row.get("gold")
    if isinstance(gold, str):
        try:
            gold = json.loads(gold)
        except Exception:
            gold = None
    if not isinstance(gold, dict) or "has_schedule" not in gold:
        stats["skipped_badgold"] += 1
        return None, None

    # 음성/통과형은 그대로. EDITED 양성만 date 상대화.
    review = None
    if fb == "EDITED" and gold.get("has_schedule"):
        rd = _recv_date(row.get("received_at", ""))
        events = gold.get("events") or []
        if rd is None:
            stats["skipped_badrecv"] += 1
            return None, None
        non_message_match = False
        for ev in events:
            if not isinstance(ev, dict):
                continue
            new_date, method = relativize_date(rd, ev.get("date"), row.get("message", ""))
            ev["date"] = new_date
            stats[f"date_{method}"] = stats.get(f"date_{method}", 0) + 1
            if method in ("canonical", "absolute-kept"):
                non_message_match = True
        if non_message_match:
            review = {**row, "gold": gold, "_review": "EDITED date 표면 미일치 — 토큰 확인"}

    pair = {
        "scenario_id": row.get("scenario_id", ""),
        "received_at": row.get("received_at", ""),
        "channel": row.get("channel", ""),
        "sender": row.get("sender", ""),
        "language": row.get("language", "ko"),
        "message": row.get("message", ""),
        "gold": gold,
        "_feedback": fb,          # 라운드 큐레이션·필터용(assemble_train.key는 무시)
        "_src": "feedback",
    }
    if row.get("thread_context"):
        pair["thread_context"] = row["thread_context"]
    return pair, review


def dedup_key(r: dict) -> str:
    """assemble_train.key 와 동일 규칙(채널+메시지+gold)으로 사전 중복 제거."""
    return f"{r.get('channel','')}|{r.get('message','')}|{json.dumps(r.get('gold',{}), ensure_ascii=False, sort_keys=True)}"


def is_pos(r: dict) -> bool:
    return bool(r.get("gold", {}).get("has_schedule"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", nargs="*",
                    help="입력 JSONL(들). 미지정 시 data/feedback_raw/*.jsonl")
    ap.add_argument("--round", default="r19", help="라운드 토큰(출력 파일명에 사용)")
    ap.add_argument("--out", default=None, help="기본 data/processed/feedback_<round>.jsonl")
    args = ap.parse_args()

    patterns = args.inputs or ["data/feedback_raw/*.jsonl"]
    files: list[str] = []
    for p in patterns:
        files += sorted(glob.glob(p))
    # review 산출물은 입력으로 다시 먹지 않음
    files = [f for f in files if not f.endswith("_review.jsonl")]
    if not files:
        print(f"! 입력 없음: {patterns}")
        print("  폰 설정 → '학습 데이터 보내기'로 받은 feedback_export.jsonl 을 data/feedback_raw/ 에 두세요.")
        return

    stats = {"skipped_badgold": 0, "skipped_badrecv": 0}
    pairs, reviews, seen = [], [], set()
    dup = 0
    for fpath in files:
        with open(fpath, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    stats["skipped_badgold"] += 1
                    continue
                pair, review = process_row(row, stats)
                if pair is None:
                    continue
                k = dedup_key(pair)
                if k in seen:
                    dup += 1
                    continue
                seen.add(k)
                pairs.append(pair)
                if review is not None:
                    reviews.append(review)

    out = args.out or f"data/processed/feedback_{args.round}.jsonl"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in pairs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 리포트
    by_fb: dict[str, int] = {}
    pos = neg = 0
    for r in pairs:
        by_fb[r["_feedback"]] = by_fb.get(r["_feedback"], 0) + 1
        pos += is_pos(r); neg += not is_pos(r)
    total = len(pairs)
    print(f"=== ingest_feedback ({args.round}) — 입력 {len(files)}파일 ===")
    print(f"  학습 페어 {total}건  (양성 {pos} / 음성 {neg}, 음성 {neg/total:.0%})" if total else "  학습 페어 0건")
    print(f"  _feedback별: " + ", ".join(f"{k}={v}" for k, v in sorted(by_fb.items())))
    dmethods = {k[5:]: v for k, v in stats.items() if k.startswith("date_")}
    if dmethods:
        print(f"  EDITED date 변환: " + ", ".join(f"{k}={v}" for k, v in sorted(dmethods.items())))
    print(f"  중복 제외 {dup} · gold불량 {stats['skipped_badgold']} · 수신시각불량 {stats['skipped_badrecv']}")
    print(f"→ {out}")

    if reviews:
        rpath = f"data/feedback_raw/{args.round}_review.jsonl"
        Path(rpath).parent.mkdir(parents=True, exist_ok=True)
        with open(rpath, "w", encoding="utf-8") as f:
            for r in reviews:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  ⚠ EDITED 표면 미일치 {len(reviews)}건 → {rpath} (토큰 직접 확인 권장)")

    if total:
        print("\n다음: assemble_train.SOURCES 에 추가 →")
        print(f'    {{"path": "{out}", "kind": "keep", "real": True}},')
        print("  그리고  python scripts/assemble_train.py  로 미리보기 후 --apply.")


if __name__ == "__main__":
    main()
