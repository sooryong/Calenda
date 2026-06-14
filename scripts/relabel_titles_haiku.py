"""제목 전체 재라벨 (Haiku) — 새 '자연제목 보존' 규칙으로 양성 gold의 title만 재생성.

규칙(2026-06-14 결정): 모델 title = 메시지의 일정 제목/주제 문구를 '시간(날짜·시각)만 제외'하고
최대한 보존. 활동-only로 줄이지 않음. 참석자·장소가 제목 문구에 녹아 있으면 보존.
단 '장소: ???' 라벨 분리형은 제외(위치 필드). 인사·서명·잡담(ㅋㅋ/ㄱㄱ/늦지마) 제외.
멀티턴 '네'류 확정은 thread의 제안 문구에서 제목을 가져옴.

title 필드만 바꾼다 — date/time/location/attendees/confidence/has_schedule 전부 불가침.

사용:
    python scripts/relabel_titles_haiku.py                 # train.jsonl dry-run(샘플+통계)
    python scripts/relabel_titles_haiku.py --apply         # train.jsonl 갱신
    python scripts/relabel_titles_haiku.py --in data/eval/golden.jsonl --apply   # 골든도
    python scripts/relabel_titles_haiku.py --limit 20      # 20건만(시험)
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import call_claude, extract_json_block

SYSTEM = """너는 일정 '제목 재라벨러'다. 주어진 메시지에서 일정의 자연스러운 제목을 뽑아 JSON {"title": "..."} 하나만 출력한다.

규칙:
1. 메시지의 일정 제목/주제 문구를 **시간(날짜·시각) 표현만 제외**하고 **최대한 그대로 보존**한다. 활동 한 단어로 줄이지 마라.
   - "내일 13시 AWS 교육팀과 줌회의" → {"title": "AWS 교육팀과 줌회의"}
   - "내일 오후1시 AWS 교육관련 온라인 회의" → {"title": "AWS 교육관련 온라인 회의"}
   - "모레 3시 주간회의 합시다" → {"title": "주간회의"}
2. 참석자·장소가 제목 문구에 녹아 있으면 **함께 보존**한다("민지와 강남역 저녁", "회사 3층 회의").
3. 단, 장소가 **"장소: ???"처럼 라벨로 분리** 제공되면 제목에서 **제외**한다(위치 필드로 가므로).
4. 인사말·서명·잡담·이모티콘(ㅋㅋ, ㄱㄱ, 늦지마, ^^, 안녕하세요, ~드림)은 제외한다.
5. 긴 메일은 본문 전체가 아니라 **그 일정의 안건/제목 문구**만 보존한다.
6. 멀티턴 대화에서 마지막이 "네/좋습니다" 같은 확정이면, **직전 제안 메시지**에서 제목을 가져온다.
7. 힌트로 주는 현재 제목/장소/참석자는 **어떤 이벤트인지 식별용**이다 — 그 이벤트의 자연 제목을 뽑되, 힌트 제목을 그대로 베끼지 말고 위 규칙대로 보존형으로 만든다.

JSON 외 다른 말은 출력하지 마라."""


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
    lines.append(f"위 메시지의 일정 이벤트(식별 힌트 — 현재제목: {ev.get('title')!r}, "
                 f"장소: {ev.get('location')!r}, 참석자: {ev.get('attendees')}) 의 자연 제목을 출력하라.")
    return "\n".join(lines)


def relabel_one(rec: dict, ev: dict) -> str | None:
    try:
        raw = call_claude(SYSTEM, build_prompt(rec, ev), temperature=0.2, max_tokens=200)
        obj = json.loads(extract_json_block(raw))
        t = (obj.get("title") or "").strip()
        return t or None
    except Exception as e:
        print(f"  ! 실패: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/processed/train.jsonl")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    path = Path(args.inp)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # (row_idx, ev_idx) 작업 목록 — 양성만
    tasks = []
    for ri, r in enumerate(rows):
        if not r.get("gold", {}).get("has_schedule"):
            continue
        for ei, ev in enumerate(r["gold"].get("events", [])):
            tasks.append((ri, ei))
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"{path.name}: 양성 이벤트 {len(tasks)}건 재라벨 (workers={args.workers})")

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(relabel_one, rows[ri], rows[ri]["gold"]["events"][ei]): (ri, ei) for ri, ei in tasks}
        done = 0
        for fut in as_completed(futs):
            ri, ei = futs[fut]
            results[(ri, ei)] = fut.result()
            done += 1
            if done % 50 == 0:
                print(f"  ...{done}/{len(tasks)}")

    changed = 0
    samples = []
    for (ri, ei), new in results.items():
        old = rows[ri]["gold"]["events"][ei].get("title")
        if new and new != old:
            changed += 1
            if len(samples) < 20:
                samples.append((rows[ri].get("message", "")[:60], old, new))
            if args.apply:
                rows[ri]["gold"]["events"][ei]["title"] = new
    print(f"\n변경 {changed}/{len(results)}건. 샘플:")
    for msg, old, new in samples:
        print(f"  msg: {msg}")
        print(f"    {old!r}  ->  {new!r}")

    if args.apply:
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        print(f"\n✓ {path} 갱신 ({changed}건 제목 변경)")
    else:
        print("\ndry-run (적용하려면 --apply)")


if __name__ == "__main__":
    main()
