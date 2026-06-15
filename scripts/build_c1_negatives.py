"""c1 음성 생성 (Haiku, criterion 기반) — 멀티턴 미확정 + 단일 통보.

음성 gold는 {has_schedule:false, events:[]}로 스키마 무관 → 생성기를 Haiku로 직접 구동(stale generator.md 우회).
생성 후 scripts/audit_schedule.py로 이중판정(evaluator) → Haiku도 음성이라 확인한 것만 채택.

카테고리:
  - B 멀티턴 음성: 일정 논의하나 **확정 미도달**(마지막이 새 제안/질문/유보/거절/취소). thread_context 포함.
  - 단일 통보 음성: 날짜·시각 품은 비-일정(카드승인·결제·적립·인증·영업연락·정기결제).

사용:
    python scripts/build_c1_negatives.py --mt 160 --single 60 --out data/processed/_c1_neg.jsonl
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import call_claude, extract_json_block

RECV = "2026-06-15T10:00:00+09:00"

MT_SYSTEM = """너는 한국어 카카오톡 대화 데이터 생성기다. **일정을 논의하지만 확정에 도달하지 않은** 대화 스레드를 만든다.
마지막 메시지는 반드시 다음 중 하나로 끝난다(확정 아님):
 - 새 제안/질문: "화요일 오후 어때요?", "그날 시간 되세요?"
 - 유보/모호: "조만간 한번 보자", "다음 주쯤 다시 잡을게요"(구체 시각 없음)
 - 거절: "그날은 다른 일정이 있어서 다음에 봬요"
 - 취소: "미안, 그 약속 취소해야 할 것 같아"
다양한 관계(친구·동료·거래처·가족)·말투·주제. 실제 대화처럼 자연스럽게(2~4개 직전 메시지 + 마지막 1개).

각 항목을 JSON 한 줄로 출력(JSONL), 다른 말 금지:
{"channel":"kakao","sender":"<마지막 발신자>","thread":[{"time":"HH:MM","sender":"...","message":"..."},...],"message":"<마지막 메시지>"}"""

SINGLE_SYSTEM = """너는 한국어 기계 발신 알림 데이터 생성기다. **날짜·시각이 들어있지만 일정이 아닌 통보** 메시지를 만든다.
유형(고루 섞어라): 카드 승인·결제·출금·청구 / 정기결제 예정 / 포인트·적립·멤버십·별 소멸 / 인증·로그인 보안 / 영업·상담 연락약속("오후 3시쯤 연락드릴게요") / 구독 갱신.
★ 반드시 날짜 또는 시각을 포함하되, **사용자가 그 시각에 직접 행동하지 않는** 자동 통보여야 한다(일정 아님).
발신자는 기관/서비스/영업담당(카카오페이·토스·KB국민은행·신한카드·현대카드·SKT·Starbucks Korea·넷플릭스·보험설계사 등) 다양하게.

각 항목을 JSON 한 줄로 출력(JSONL), 다른 말 금지:
{"channel":"kakao","sender":"<발신자>","message":"<통보 메시지(날짜·시각 포함)>"}"""


def gen_batch(system: str, n: int, seed_hint: str) -> list[dict]:
    user = f"{n}개를 생성하라. 서로 최대한 다른 주제·발신자·표현으로. ({seed_hint})"
    try:
        raw = call_claude(system, user, temperature=1.0, max_tokens=4000)
        rows = []
        for line in raw.splitlines():
            line = line.strip().strip("`").strip()
            if not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows
    except Exception as e:
        print("  ! batch 실패:", e)
        return []


def to_record(obj: dict, sid: str) -> dict | None:
    msg = (obj.get("message") or "").strip()
    if not msg:
        return None
    rec = {"scenario_id": sid, "received_at": RECV, "channel": obj.get("channel", "kakao"),
           "sender": obj.get("sender", ""), "language": "ko", "message": msg,
           "gold": {"has_schedule": False, "events": []}}
    th = obj.get("thread")
    if th:
        rec["thread_context"] = [{"time": t.get("time", ""), "sender": t.get("sender", ""),
                                  "message": t.get("message", "")} for t in th if t.get("message")]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mt", type=int, default=160, help="멀티턴 음성 목표")
    ap.add_argument("--single", type=int, default=60, help="단일 통보 음성 목표")
    ap.add_argument("--out", default="data/processed/_c1_neg.jsonl")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    jobs = []  # (system, n, hint, sid_prefix)
    B = 8  # 배치당 생성 수
    for i in range((args.mt + B - 1) // B):
        jobs.append((MT_SYSTEM, min(B, args.mt - i * B), f"멀티턴 배치{i}", "c1_mtneg"))
    for i in range((args.single + B - 1) // B):
        jobs.append((SINGLE_SYSTEM, min(B, args.single - i * B), f"통보 배치{i}", "c1_singleneg"))

    out_rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(gen_batch, s, n, h): pre for (s, n, h, pre) in jobs}
        done = 0
        for fut in as_completed(futs):
            pre = futs[fut]
            for j, obj in enumerate(fut.result()):
                r = to_record(obj, f"{pre}_{done}_{j}")
                if r:
                    out_rows.append(r)
            done += 1
            print(f"  배치 {done}/{len(jobs)} 누적 {len(out_rows)}")

    mt = sum(1 for r in out_rows if r["scenario_id"].startswith("c1_mtneg"))
    sg = sum(1 for r in out_rows if r["scenario_id"].startswith("c1_singleneg"))
    Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n", encoding="utf-8")
    print(f"\n생성 {len(out_rows)} (멀티턴 {mt} · 단일통보 {sg}) → {args.out}")
    print("→ 다음: python scripts/audit_schedule.py --in {out} 로 이중검증(전부 음성 확인)".format(out=args.out))


if __name__ == "__main__":
    main()
