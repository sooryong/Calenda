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


def _start_flat(received_at, ev: dict) -> str | None:
    """플랫 이벤트의 date/time 토큰 → 절대 start ISO (resolver 경유)."""
    return resolve_when(received_at, ev.get("date"), ev.get("time"), ev.get("end_time"))["start"]


def score_fields(received_at, gold: dict, pred: dict) -> dict:
    """플랫 스키마 채점. is_schedule은 별도 집계, 여기선 추출 품질만.
    gold·pred 모두 플랫 dict (is_schedule, title, date, time, location, description)."""
    title_f1 = title_score(gold.get("title"), pred.get("title"))
    g_start = _start_flat(received_at, gold)
    p_start = _start_flat(received_at, pred)
    time_f1 = 1.0 if time_match(g_start, p_start) else 0.0
    loc_f1  = location_score(gold.get("location"), pred.get("location"))
    return {"title_f1": title_f1, "time_f1": time_f1, "loc_f1": loc_f1}


def load_model(path: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(
        path, dtype=torch.float16, device_map="auto"
    )
    model.eval()
    return model, tok


def infer(model, tok, system: str, sample: dict, max_new_tokens: int = 512, supports_system: bool = True) -> str:
    user_block = build_user_block(sample)  # thread_context 있으면 <대화내역> 블록 자동 삽입
    if supports_system:
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_block},
        ]
    else:
        # Gemma 등 system 역할 미지원: system을 첫 user 턴 접두로 합침 (학습 렌더와 동일)
        msgs = [
            {"role": "user", "content": system + "\n\n" + user_block},
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
        attention_mask = encoded.attention_mask.to(model.device) if hasattr(encoded, "attention_mask") else (input_ids != tok.pad_token_id).long()
    else:
        input_ids = encoded.to(model.device)
        attention_mask = (input_ids != tok.pad_token_id).long()
    out = model.generate(
        input_ids,
        attention_mask=attention_mask,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tok.eos_token_id,
    )
    text = tok.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True)
    return text.strip()


def run_eval(samples, infer_fn, out=None, failures_out=None):
    """샘플을 infer_fn(sample)->raw로 추론하고 채점·집계해 metrics 반환.

    플랫 스키마(is_schedule + 개별 필드) 기준.
    eval_model(HF transformers)과 eval_gguf(llama.cpp)가 **동일 채점**을 공유하기 위한
    단일 경로. 추론 방식만 infer_fn으로 주입받고, 점수 계산·집계·실패저장은 여기서 일괄.
    """
    json_valid = 0
    is_sched_correct = 0
    field_sum = {"title_f1": 0.0, "time_f1": 0.0, "loc_f1": 0.0}
    failures = []

    # 디커플링 집계: 검출(recall/specificity)과 추출품질(진짜양성 한정)을 분리해
    # 결합 지표(과발화 1건이 title/time/loc을 동시에 0으로 박는 문제)를 보완.
    pos_total = neg_total = 0
    recall_hit = spec_hit = overfire = missed = 0
    tp_n = 0
    tp_sum = {"title_f1": 0.0, "time_f1": 0.0, "loc_f1": 0.0}

    def _has(v) -> bool:
        """is_schedule 필드 → bool. true/True/"true"/"yes" = True, 나머지 False."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes")
        return False

    for sample in tqdm(samples, desc="eval"):
        raw = infer_fn(sample)
        pred = safe_json_loads(raw)

        gold = sample["gold"]
        g_has = _has(gold.get("is_schedule"))
        if g_has:
            pos_total += 1
        else:
            neg_total += 1

        if pred is None:
            if g_has:
                missed += 1
            failures.append({**sample, "_pred_raw": raw, "_reason": "json_parse_error"})
            continue

        json_valid += 1

        p_has = _has(pred.get("is_schedule"))
        status_match = (g_has == p_has)
        if status_match:
            is_sched_correct += 1

        # 검출 분해 (yes=True / no=False)
        if g_has and p_has:
            recall_hit += 1
        elif (not g_has) and (not p_has):
            spec_hit += 1
        elif (not g_has) and p_has:
            overfire += 1
        elif g_has and (not p_has):
            missed += 1

        scores = score_fields(sample["received_at"], gold, pred)
        for k in field_sum:
            field_sum[k] += scores[k]

        # 추출품질: 올바로 검출된 진짜 양성 & gold에 title이 있을 때만
        if g_has and p_has and gold.get("title"):
            tp_n += 1
            for k in tp_sum:
                tp_sum[k] += scores[k]

        # 실패 임계: is_schedule 오답 OR 추출 품질 미달 (두 기준 동등)
        if not status_match or scores["title_f1"] < 0.7 or scores["time_f1"] < 1.0:
            failures.append({**sample, "_pred": pred, "_scores": {**scores, "status_match": status_match}})

    n = len(samples)
    metrics = {
        "n": n,
        "json_valid_rate": json_valid / n,
        "is_schedule_acc": is_sched_correct / n,
        "title_f1_avg": field_sum["title_f1"] / n,
        "time_match_rate": field_sum["time_f1"] / n,
        "location_f1_avg": field_sum["loc_f1"] / n,
    }
    metrics["final_score"] = (
        0.25 * metrics["json_valid_rate"]
        + 0.30 * metrics["is_schedule_acc"]
        + 0.45 * (
            (metrics["title_f1_avg"] + metrics["time_match_rate"] + metrics["location_f1_avg"]) / 3
        )
    )

    # ── 디커플링 지표 (결합 지표의 과소평가 보정 — 라운드별 정직한 추적용) ──
    metrics["detection"] = {
        "n_pos": pos_total,
        "n_neg": neg_total,
        "recall_pos": recall_hit / max(1, pos_total),       # is_schedule=true 검출 비율
        "specificity_neg": spec_hit / max(1, neg_total),    # no를 no로 거르는 비율
        "overfire_count": overfire,                          # false→true 오발화
        "missed_count": missed,                              # true→false 누락
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
    ap.add_argument("--system_prompt", default=None, help="직접 지정. 없으면 --model_config의 system_prompt")
    ap.add_argument("--model_config", default="configs/model_qwen3_0_6b.yaml",
                    help="system_prompt 출처 config — 반드시 학습과 동일해야 함(train/eval 프롬프트 불일치 방지)")
    ap.add_argument("--failures_out", default="data/failures/round_latest.jsonl")
    args = ap.parse_args()

    import yaml
    with open(args.model_config, "r", encoding="utf-8") as f:
        _mcfg = yaml.safe_load(f)
    if args.system_prompt is None:
        args.system_prompt = _mcfg["system_prompt"]
    _supports_system = _mcfg.get("supports_system", True)

    model, tok = load_model(args.model)
    samples = list(read_jsonl(args.eval))
    run_eval(samples, lambda s: infer(model, tok, args.system_prompt, s, supports_system=_supports_system),
             out=args.out, failures_out=args.failures_out)


if __name__ == "__main__":
    main()
