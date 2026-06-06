"""학습된 모델을 골든 평가셋으로 평가.

사용:
    python scripts/eval_model.py --model models/merged/r3-qwen --eval data/eval/golden.jsonl --out logs/eval_r3-qwen.json
"""
from __future__ import annotations

import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")   # 단일 GPU (device_map auto의 2-GPU 분산 방지)

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

from rapidfuzz import fuzz
from tqdm import tqdm

from _common import build_user_block, read_jsonl, resolve_when, safe_json_loads


TIME_TOLERANCE_MIN = 5  # ±5분 허용


def parse_iso(s: str | None):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # 모델이 timezone 누락한 출력을 KST로 가정 (generator.md §7).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except Exception:
        return None


def time_match(a: str | None, b: str | None) -> bool:
    da, db = parse_iso(a), parse_iso(b)
    if da is None and db is None:
        return True
    if da is None or db is None:
        return False
    return abs((da - db).total_seconds()) <= TIME_TOLERANCE_MIN * 60


def title_score(a: str | None, b: str | None) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # 100점 만점 ratio → 0~1
    return fuzz.token_set_ratio(a, b) / 100.0


def location_score(a: str | None, b: str | None) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return fuzz.partial_ratio(a, b) / 100.0


def _start(received_at, ev: dict) -> str | None:
    """이벤트의 date/time 토큰 → 절대 start ISO (resolver 경유). 채점 단일 기준."""
    return resolve_when(received_at, ev.get("date"), ev.get("time"),
                        ev.get("end_time"), ev.get("all_day", False))["start"]


def score_events(received_at, gold_events: list, pred_events: list) -> dict:
    """1:1 매칭. 시각은 gold·pred 모두 resolver로 절대화 후 비교(새 스키마)."""
    if not gold_events and not pred_events:
        return {"event_count_match": True, "title_f1": 1.0, "time_f1": 1.0, "loc_f1": 1.0}
    if len(gold_events) != len(pred_events):
        return {"event_count_match": False, "title_f1": 0.0, "time_f1": 0.0, "loc_f1": 0.0}

    titles, times, locs = [], [], []
    for g, p in zip(gold_events, pred_events):
        titles.append(title_score(g.get("title"), p.get("title")))
        times.append(1.0 if time_match(_start(received_at, g), _start(received_at, p)) else 0.0)
        locs.append(location_score(g.get("location"), p.get("location")))

    def mean(xs): return sum(xs) / max(1, len(xs))
    return {
        "event_count_match": True,
        "title_f1": mean(titles),
        "time_f1": mean(times),
        "loc_f1": mean(locs),
    }


def load_model(path: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(
        path, torch_dtype=torch.float16, device_map="auto"
    )
    model.eval()
    return model, tok


def infer(model, tok, system: str, sample: dict, max_new_tokens: int = 512) -> str:
    user_block = build_user_block(sample)  # thread_context 있으면 <대화내역> 블록 자동 삽입
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_block},
    ]
    # transformers 5.x: apply_chat_template은 BatchEncoding 반환
    # transformers 4.x: Tensor 반환. 둘 다 호환.
    encoded = tok.apply_chat_template(msgs, return_tensors="pt", add_generation_prompt=True)
    if hasattr(encoded, "input_ids"):
        input_ids = encoded.input_ids.to(model.device)
    else:
        input_ids = encoded.to(model.device)
    out = model.generate(
        input_ids,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tok.eos_token_id,
    )
    text = tok.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", default="logs/eval_latest.json")
    ap.add_argument("--system_prompt", default=None, help="없으면 model_qwen.yaml 사용")
    ap.add_argument("--failures_out", default="data/failures/round_latest.jsonl")
    args = ap.parse_args()

    if args.system_prompt is None:
        import yaml
        with open("configs/model_qwen.yaml", "r", encoding="utf-8") as f:
            args.system_prompt = yaml.safe_load(f)["system_prompt"]

    model, tok = load_model(args.model)
    samples = list(read_jsonl(args.eval))

    json_valid = 0
    has_sched_correct = 0
    field_sum = {"title_f1": 0.0, "time_f1": 0.0, "loc_f1": 0.0}
    event_count_acc = 0
    failures = []

    # 디커플링 집계: 검출(recall/specificity)과 추출품질(진짜양성 한정)을 분리해
    # 결합 지표(과발화 1건이 title/time/loc을 동시에 0으로 박는 문제)를 보완.
    pos_total = neg_total = 0
    recall_hit = spec_hit = overfire = missed = 0
    tp_n = 0
    tp_sum = {"title_f1": 0.0, "time_f1": 0.0, "loc_f1": 0.0}

    for sample in tqdm(samples, desc="eval"):
        raw = infer(model, tok, args.system_prompt, sample)
        pred = safe_json_loads(raw)

        gold = sample["gold"]
        g_has = bool(gold.get("has_schedule"))
        if g_has:
            pos_total += 1
        else:
            neg_total += 1

        if pred is None:
            # 파싱 실패 = 유효 예측 없음 → 검출 크레딧 없음(양성이면 missed)
            if g_has:
                missed += 1
            failures.append({**sample, "_pred_raw": raw, "_reason": "json_parse_error"})
            continue

        json_valid += 1

        p_has = bool(pred.get("has_schedule"))
        if p_has == g_has:
            has_sched_correct += 1
        # 검출 분해
        if g_has and p_has:
            recall_hit += 1
        elif (not g_has) and (not p_has):
            spec_hit += 1
        elif (not g_has) and p_has:
            overfire += 1
        elif g_has and (not p_has):
            missed += 1

        gold_events = gold.get("events", [])
        pred_events = pred.get("events", [])
        scores = score_events(sample["received_at"], gold_events, pred_events)
        if scores["event_count_match"]:
            event_count_acc += 1
        for k in field_sum:
            field_sum[k] += scores[k]

        # 추출품질: 올바로 검출된 진짜 양성 & 개수 일치 & gold 이벤트 존재할 때만
        if g_has and p_has and len(gold_events) == len(pred_events) and gold_events:
            tp_n += 1
            for k in tp_sum:
                tp_sum[k] += scores[k]

        # 실패 임계
        if scores["title_f1"] < 0.7 or scores["time_f1"] < 1.0:
            failures.append({**sample, "_pred": pred, "_scores": scores})

    n = len(samples)
    metrics = {
        "n": n,
        "json_valid_rate": json_valid / n,
        "has_schedule_acc": has_sched_correct / n,
        "title_f1_avg": field_sum["title_f1"] / n,
        "time_match_rate": field_sum["time_f1"] / n,
        "location_f1_avg": field_sum["loc_f1"] / n,
        "event_count_acc": event_count_acc / n,
    }
    metrics["final_score"] = (
        0.30 * metrics["json_valid_rate"]
        + 0.25 * metrics["has_schedule_acc"]
        + 0.35 * (
            (metrics["title_f1_avg"] + metrics["time_match_rate"] + metrics["location_f1_avg"]) / 3
        )
        + 0.10 * metrics["event_count_acc"]
    )

    # ── 디커플링 지표 (결합 지표의 과소평가 보정 — 라운드별 정직한 추적용) ──
    metrics["detection"] = {
        "n_pos": pos_total,
        "n_neg": neg_total,
        "recall_pos": recall_hit / max(1, pos_total),       # 진짜 일정을 잡는 비율
        "specificity_neg": spec_hit / max(1, neg_total),    # 일정 아닌 걸 거르는 비율(과발화의 역)
        "overfire_count": overfire,                          # 음성→양성 오발화
        "missed_count": missed,                              # 양성→음성 누락
    }
    metrics["extraction_on_true_positives"] = {              # 올바로 검출된 양성에 한한 추출 품질
        "n": tp_n,
        "title_avg": tp_sum["title_f1"] / max(1, tp_n),
        "time_acc": tp_sum["time_f1"] / max(1, tp_n),
        "loc_avg": tp_sum["loc_f1"] / max(1, tp_n),
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    # 실패 저장 (다음 폐루프 입력)
    if failures:
        Path(args.failures_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.failures_out, "w", encoding="utf-8") as f:
            for r in failures:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[eval] 실패 {len(failures)}건 → {args.failures_out}")


if __name__ == "__main__":
    main()
