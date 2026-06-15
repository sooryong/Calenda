"""필드 정합 재라벨 (Haiku) — 양성 gold의 location·attendees를 메시지 근거로 재생성.

배경(r32 실사용): 제목 자연보존은 성공했으나 모델이 보조 필드를 잘못 채움.
  - location 비움(제목에만 보존) 또는 **제목을 location에 복제**(대구TP간담회 케이스).
  - attendees 추측/환각.
→ r33: location·attendees를 메시지에 실제로 등장한 표현으로만 재라벨.
  title/date/time/end_time/all_day/organizer/description/recurrence/confidence/has_schedule 전부 불가침.

규칙(= prompts/schema.md):
  - location: 메시지에 명시된 물리 장소 또는 온라인 도구(줌·구글밋·팀즈·전화·화상·온라인…)만. 없으면 null.
    ★ 제목/행사명/안건을 location에 복제 금지.
  - attendees: 메시지에 실제 등장하는 사람·팀 이름만. 없으면 []. 발신자 자신은 보통 제외.

★ Haiku 출력은 신뢰하되 **결정론적 가드로 검증**한다:
  - location == title(정규화) → null (복제 차단)
  - location이 메시지에 grounding 안 되면 → null (환각 차단; 온라인 도구는 동의어 허용)
  - attendees 중 메시지·대화내역에 등장하지 않는 이름 → 제거

사용:
    python scripts/relabel_fields_haiku.py                         # train.jsonl dry-run(샘플+통계)
    python scripts/relabel_fields_haiku.py --limit 30              # 30건만(시험)
    python scripts/relabel_fields_haiku.py --apply                 # train.jsonl 갱신
    python scripts/relabel_fields_haiku.py --in data/eval/golden.jsonl --apply   # 골든도
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import call_claude, extract_json_block

SYSTEM = """너는 일정의 '장소(location)'와 '참석자(attendees)' 필드 재라벨러다.
주어진 메시지에서 두 필드만 뽑아 JSON {"location": ..., "attendees": [...]} 하나만 출력한다.

규칙:
1. location = 메시지에 **명시된** 장소만 넣는다.
   - 물리 장소: "회사 3층", "강남역 2번출구", "서울내과", "본사 대회의실", "합정 스타벅스" 등.
   - 교통 출발지도 장소로: "인천공항", "Bangkok Suvarnabhumi Airport (BKK)", "서울역", "강남고속터미널" 등.
   - 온라인 회의 도구도 장소로: "줌", "구글밋", "팀즈", "페이스타임", "전화", "화상", "온라인", "웹엑스".
     ("줌으로/화상으로/전화로 미팅" → location:"줌"/"화상"/"전화")
   - ★ 장소가 메시지에 없으면 **location: null**. 절대 지어내지 마라.
   - ★ **제목/행사명/안건을 location에 복제 금지** — 행사 이름은 장소가 아니다.
     (예: "대구TP 간담회"·"신제품 출시 간담회"는 제목이지 장소가 아니다 → 장소가 따로 없으면 location:null.
      반면 "연남동 카페"·"강남역 카라오케"는 실제 장소이므로 location에 넣는다.)
2. attendees = 메시지에 **실제 등장하는 사람·팀 이름**만 배열로. (예: "박과장", "민지", "마케팅팀")
   - 발신자 자신은 보통 제외(단 "팀장님이 호스트"처럼 명시적 참석자면 포함).
   - 없으면 **attendees: []**. 추측·환각 금지. 제목/장소 문구를 참석자로 넣지 마라.
3. 힌트로 주는 현재 제목/장소/참석자는 **어떤 이벤트인지 식별용**일 뿐 — 그대로 베끼지 말고 메시지 근거로 다시 판단하라.
4. 멀티턴 대화에서 마지막이 "네/좋습니다" 확정이면, 직전 제안 메시지의 장소·참석자를 본다.

JSON 외 다른 말은 출력하지 마라. 예: {"location": "줌", "attendees": ["박과장"]} / {"location": null, "attendees": []}"""

# 온라인 도구 동의어(정규화 비교용) — grounding 시 도구 키워드 존재로 허용
TOOL_CANON = ["줌", "구글밋", "구글미트", "미트", "팀즈", "페이스타임", "전화", "화상",
              "온라인", "웹엑스", "행아웃", "스카이프", "비대면", "영상통화", "보이스톡"]


def norm(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


def gather_text(rec: dict) -> str:
    parts = [rec.get("message", "")]
    for t in rec.get("thread_context") or []:
        parts.append(t.get("message", ""))
    return norm(" ".join(parts))


def build_prompt(rec: dict, ev: dict) -> str:
    lines = [f"<채널>{rec.get('channel','')}</채널>", f"<발신자>{rec.get('sender','')}</발신자>"]
    th = rec.get("thread_context") or []
    if th:
        lines.append("<대화내역>")
        for t in th:
            lines.append(f"  [{t.get('sender','')}] {t.get('message','')}")
        lines.append("</대화내역>")
    lines.append(f"<메시지>{rec.get('message','')}</메시지>")
    lines.append("")
    lines.append(f"위 메시지의 일정 이벤트(식별 힌트 — 제목: {ev.get('title')!r}, "
                 f"현재장소: {ev.get('location')!r}, 현재참석자: {ev.get('attendees')}) 의 "
                 f"location·attendees를 메시지 근거로 출력하라.")
    return "\n".join(lines)


def relabel_one(rec: dict, ev: dict):
    try:
        raw = call_claude(SYSTEM, build_prompt(rec, ev), temperature=0.2, max_tokens=200)
        obj = json.loads(extract_json_block(raw))
        loc = obj.get("location")
        att = obj.get("attendees")
        loc = (loc or "").strip() or None
        att = [a.strip() for a in (att or []) if isinstance(a, str) and a.strip()]
        return {"location": loc, "attendees": att}
    except Exception as e:
        print(f"  ! 실패: {e}")
        return None


def grounded_loc(loc: str | None, text: str) -> bool:
    """location이 메시지에 근거하는가 (온라인 도구는 동의어 허용)."""
    if not loc:
        return False
    nloc = norm(loc)
    if nloc in text:
        return True
    # 온라인 도구: 메시지에 도구 키워드가 있고 loc도 도구류면 허용
    return any(tc in text for tc in TOOL_CANON) and any(tc in nloc or nloc in tc for tc in TOOL_CANON)


def guard(rec: dict, ev: dict, out: dict) -> dict:
    """보수적 가드 — 실제 장소/참석자는 보호, 환각·발신자·미근거만 제거.

    location: Haiku의 grounded 값 우선 → 없으면 기존 grounded 값 유지(공항·카페 등 손실 방지).
              둘 다 grounded 아니면 null.  ★ Haiku가 grounded 장소를 임의로 null 못 함.
    attendees: (기존 ∪ Haiku) 중 메시지·대화내역에 등장하는 이름만(발신자·환각 제거).
    """
    text = gather_text(rec)
    old_loc = ev.get("location")
    new_loc = out["location"]

    # location = 채움 전용. 기존 장소는 신뢰(r22 anonymizer 수정 후 환각 소멸)하여 보존 —
    # 절대 제거·변경하지 않는다(공항 등 풍부한 gold가 메시지 약식형보다 길어 grounding 실패해도 손실 방지).
    # title-dup 행사명은 학습셋에 없음(audit: ==title 18건 전부 실제 장소). 빈 location만 grounded 값으로 채운다.
    if old_loc:
        loc, reason = old_loc, None
    elif grounded_loc(new_loc, text):
        loc, reason = new_loc, "fill"
    else:
        loc, reason = None, None

    old_att = list(ev.get("attendees") or [])
    cand, seen = [], set()
    for a in old_att + out["attendees"]:
        if a not in seen:
            seen.add(a); cand.append(a)
    att_kept = [a for a in cand if norm(a) and norm(a) in text]
    att_dropped = [a for a in old_att if a not in att_kept]

    return {"location": loc, "attendees": att_kept,
            "_loc_reason": reason, "_att_dropped": att_dropped}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/processed/train.jsonl")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    path = Path(args.inp)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    tasks = []
    for ri, r in enumerate(rows):
        if not r.get("gold", {}).get("has_schedule"):
            continue
        for ei, ev in enumerate(r["gold"].get("events", [])):
            tasks.append((ri, ei))
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"{path.name}: 양성 이벤트 {len(tasks)}건 필드 재라벨 (workers={args.workers})")

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(relabel_one, rows[ri], rows[ri]["gold"]["events"][ei]): (ri, ei)
                for ri, ei in tasks}
        done = 0
        for fut in as_completed(futs):
            ri, ei = futs[fut]
            results[(ri, ei)] = fut.result()
            done += 1
            if done % 50 == 0:
                print(f"  ...{done}/{len(tasks)}")

    # 통계 + 적용
    loc_fill = att_added = att_changed = att_drop_total = 0
    samples = []
    for (ri, ei), out in results.items():
        if out is None:
            continue
        ev = rows[ri]["gold"]["events"][ei]
        g = guard(rows[ri], ev, out)
        old_loc, old_att = ev.get("location"), list(ev.get("attendees") or [])
        new_loc, new_att = g["location"], g["attendees"]
        if g["_loc_reason"] == "fill":
            loc_fill += 1
        att_drop_total += len(g["_att_dropped"])
        att_added += len([a for a in new_att if a not in old_att])

        att_diff = sorted(new_att) != sorted(old_att)
        if att_diff:
            att_changed += 1
        if (((new_loc or None) != (old_loc or None)) or att_diff) and len(samples) < 25:
            samples.append((rows[ri].get("message", "")[:55], (old_loc, old_att),
                            (new_loc, new_att), g["_loc_reason"], g["_att_dropped"]))
        if args.apply:
            ev["location"] = new_loc
            ev["attendees"] = new_att

    print(f"\nlocation: 빈칸 채움 {loc_fill} (기존 장소는 보존, 총 {len(results)} 이벤트)")
    print(f"attendees: 변경 {att_changed} (추가 {att_added} · 환각/발신자 제거 {att_drop_total})")
    print("샘플(변경분):")
    for msg, old, new, lr, ad in samples:
        print(f"  msg: {msg}")
        print(f"    loc/att  {old}  ->  {new}" + (f"   [loc:{lr}]" if lr else "") +
              (f"   [att제거:{ad}]" if ad else ""))

    if args.apply:
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                        encoding="utf-8")
        print(f"\n✓ {path} 갱신 (location 채움 {loc_fill} · attendees 변경 {att_changed})")
    else:
        print("\ndry-run (적용하려면 --apply)")


if __name__ == "__main__":
    main()
