"""평가 점수 진단 — 메트릭 디커플링 + 골든 감사용 per-item 덤프.

목적: final_score가 낮은 게 (a)모델 추출력 (b)검출-추출 결합 메트릭 (c)골든 오라벨 중
무엇 때문인지 가른다.

핵심: 기존 eval_model은 title/time/loc F1을 음성 포함 n 전체로 평균하고, 검출 틀린 샘플은
event 개수 불일치로 세 지표를 0으로 박는다 → 추출 품질이 검출 오류에 오염됨.
여기선 '올바로 검출된 양성'에 한해 추출 품질을 따로 본다.

사용: python scripts/audit_eval.py --model models/merged/r15-qwen0.5b --eval data/eval/golden.jsonl
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

from eval_model import load_model, infer, title_score, time_match, location_score, _start
from _common import read_jsonl, safe_json_loads
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", default="logs/audit_r15.json")
    args = ap.parse_args()

    system = yaml.safe_load(open("configs/model_qwen3_0_6b.yaml", encoding="utf-8"))["system_prompt"]
    model, tok = load_model(args.model)
    samples = list(read_jsonl(args.eval))

    items = []
    for s in samples:
        raw = infer(model, tok, system, s, max_new_tokens=256)
        pred = safe_json_loads(raw)
        gold = s["gold"]
        g_has = bool(gold.get("has_schedule"))
        if pred is None:
            items.append({"id": s.get("scenario_id"), "ch": s.get("channel"), "parse_error": True,
                          "g_has": g_has, "raw": raw[:200]})
            continue
        p_has = bool(pred.get("has_schedule"))
        ge, pe = gold.get("events", []), pred.get("events", [])
        rec = s["received_at"]
        it = {"id": s.get("scenario_id"), "ch": s.get("channel"),
              "g_has": g_has, "p_has": p_has, "g_n": len(ge), "p_n": len(pe),
              "msg": s.get("message", "")[:60]}
        if g_has and p_has and len(ge) == len(pe) and ge:
            g, p = ge[0], pe[0]
            it["title"] = round(title_score(g.get("title"), p.get("title")), 2)
            it["time"] = 1 if time_match(_start(rec, g), _start(rec, p)) else 0
            it["loc"] = round(location_score(g.get("location"), p.get("location")), 2)
            it["g_title"], it["p_title"] = g.get("title"), p.get("title")
            it["g_start"], it["p_start"] = _start(rec, g), _start(rec, p)
            it["g_loc"], it["p_loc"] = g.get("location"), p.get("location")
        items.append(it)

    n = len(items)
    det_ok = sum(1 for it in items if it.get("g_has") == it.get("p_has"))
    pos = [it for it in items if it.get("g_has")]
    neg = [it for it in items if it.get("g_has") is False]
    overfired = [it for it in neg if it.get("p_has")]          # 음성인데 양성 예측
    missed = [it for it in pos if not it.get("p_has")]         # 양성인데 음성 예측
    # 올바로 검출된 양성(개수도 일치)에 한한 추출 품질
    tp = [it for it in pos if it.get("p_has") and it.get("g_n") == it.get("p_n") and "time" in it]
    def avg(key): return round(sum(it[key] for it in tp) / max(1, len(tp)), 3)

    report = {
        "n": n,
        "detection_acc": round(det_ok / n, 3),
        "n_pos": len(pos), "n_neg": len(neg),
        "recall_pos": round(sum(1 for it in pos if it.get("p_has")) / max(1, len(pos)), 3),
        "specificity_neg": round(sum(1 for it in neg if not it.get("p_has")) / max(1, len(neg)), 3),
        "overfire_count": len(overfired),
        "missed_count": len(missed),
        "extraction_on_true_positives": {
            "n": len(tp), "title_avg": avg("title"), "time_acc": avg("time"), "loc_avg": avg("loc"),
        },
        "overfired_negatives": [{"id": it["id"], "ch": it["ch"], "msg": it["msg"]} for it in overfired],
        "missed_positives": [{"id": it["id"], "ch": it["ch"], "msg": it["msg"]} for it in missed],
        "true_positive_items": [
            {k: it.get(k) for k in ("id", "ch", "title", "time", "loc",
                                     "g_title", "p_title", "g_start", "p_start", "g_loc", "p_loc")}
            for it in tp
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "n", "detection_acc", "n_pos", "n_neg", "recall_pos", "specificity_neg",
        "overfire_count", "missed_count", "extraction_on_true_positives")}, ensure_ascii=False, indent=2))
    print(f"→ full per-item report: {args.out}")


if __name__ == "__main__":
    main()
