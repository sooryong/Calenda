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
    # 마감/종일: 한쪽이 날짜만(start에 'T' 없음)이면 날짜로만 비교 →
    # all_day(시간없음) ↔ 시각(예: 18시까지 접수) 둘 다 정답 처리(제품 결정).
    if (a and "T" not in a) or (b and "T" not in b):
        return da.date() == db.date()
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
    # Qwen3 등 thinking 모델: non-thinking은 빈 <think></think> 블록으로 표현된다.
    # 학습 렌더가 assistant 턴에 항상 <think>\n\n</think>\n\n{json}을 넣으므로(템플릿 강제),
    # 추론도 enable_thinking=False로 프롬프트에 빈 think 블록을 미리 채워 순수 JSON만 생성하게
    # 맞춰야 학습 분포와 일치한다. 안 맞추면 모델이 <think> prefix를 뱉어 JSON 파싱이 깨진다.
    # Qwen2.5는 템플릿에 enable_thinking이 없어 kwarg 미전달(동작 불변).
    extra = {}
    if "enable_thinking" in (getattr(tok, "chat_template", None) or ""):
        extra["enable_thinking"] = False
    # transformers 5.x: apply_chat_template은 BatchEncoding 반환
    # transformers 4.x: Tensor 반환. 둘 다 호환.
    encoded = tok.apply_chat_template(msgs, return_tensors="pt", add_generation_prompt=True, **extra)
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


def run_eval(samples, infer_fn, out=None, failures_out=None):
    """샘플을 infer_fn(sample)->raw로 추론하고 채점·집계해 metrics 반환.

    eval_model(HF transformers)과 eval_gguf(llama.cpp)가 **동일 채점**을 공유하기 위한
    단일 경로. 추론 방식만 infer_fn으로 주입받고, 점수 계산·집계·실패저장은 여기서 일괄.
    """
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
    # 3-way (yes/pending/no): detected = yes+pending. class_correct = yes/pending 구분까지 맞춤.
    def _cls(v):
        if v is True:
            return "yes"
        if v in (False, None):
            return "no"
        s = str(v).strip().lower()
        return s if s in ("yes", "pending", "no") else "no"

    def _det(v):
        return _cls(v) in ("yes", "pending")

    class_both = class_correct = 0  # 양쪽 detected일 때 yes/pending 일치

    for sample in tqdm(samples, desc="eval"):
        raw = infer_fn(sample)
        pred = safe_json_loads(raw)

        gold = sample["gold"]
        g_cls = _cls(gold.get("schedule_status"))
        g_has = g_cls in ("yes", "pending")
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

        p_cls = _cls(pred.get("schedule_status"))
        p_has = p_cls in ("yes", "pending")
        if p_cls == g_cls:
            has_sched_correct += 1                 # 3-way 정확 매치
        # 검출 분해 (detected = yes+pending)
        if g_has and p_has:
            recall_hit += 1
            class_both += 1
            if p_cls == g_cls:
                class_correct += 1                 # yes/pending 구분까지 맞춤
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
        "schedule_status_acc": has_sched_correct / n,
        "title_f1_avg": field_sum["title_f1"] / n,
        "time_match_rate": field_sum["time_f1"] / n,
        "location_f1_avg": field_sum["loc_f1"] / n,
        "event_count_acc": event_count_acc / n,
    }
    metrics["final_score"] = (
        0.30 * metrics["json_valid_rate"]
        + 0.25 * metrics["schedule_status_acc"]
        + 0.35 * (
            (metrics["title_f1_avg"] + metrics["time_match_rate"] + metrics["location_f1_avg"]) / 3
        )
        + 0.10 * metrics["event_count_acc"]
    )

    # ── 디커플링 지표 (결합 지표의 과소평가 보정 — 라운드별 정직한 추적용) ──
    metrics["detection"] = {
        "n_pos": pos_total,
        "n_neg": neg_total,
        "recall_pos": recall_hit / max(1, pos_total),       # 일정(yes+pending) 검출 비율
        "specificity_neg": spec_hit / max(1, neg_total),    # no를 no로 거르는 비율(과발화의 역)
        "overfire_count": overfire,                          # no→yes/pending 오발화
        "missed_count": missed,                              # yes/pending→no 누락
        "class_acc": class_correct / max(1, class_both),    # 검출된 것 중 yes/pending 구분 정확도
    }
    metrics["extraction_on_true_positives"] = {              # 올바로 검출된 양성에 한한 추출 품질
        "n": tp_n,
        "title_avg": tp_sum["title_f1"] / max(1, tp_n),
        "time_acc": tp_sum["time_f1"] / max(1, tp_n),
        "loc_avg": tp_sum["loc_f1"] / max(1, tp_n),
    }

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(metrics, ensure_ascii=False, indent=2))

    # 실패 저장 (다음 폐루프 입력)
    if failures and failures_out:
        Path(failures_out).parent.mkdir(parents=True, exist_ok=True)
        with open(failures_out, "w", encoding="utf-8") as f:
            for r in failures:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[eval] 실패 {len(failures)}건 → {failures_out}")

    return metrics


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
    run_eval(samples, lambda s: infer(model, tok, args.system_prompt, s),
             out=args.out, failures_out=args.failures_out)


if __name__ == "__main__":
    main()
