"""LoRA 학습 스크립트 (Qwen3-0.6B).

사용:
    python scripts/train_lora.py --config configs/train_qwen3_0_6b.yaml

전제: pip install -e .[train]
"""
from __future__ import annotations

import os
import warnings

# DDP barrier()의 device_id 미지정 경고 억제 — HF Trainer/accelerate 내부 init_process_group에서
# 나오는 정보성 경고(학습엔 무영향, 각 프로세스가 LOCAL_RANK GPU 사용). 로그만 깨끗이.
warnings.filterwarnings("ignore", message=r".*barrier\(\).*device_id.*")

# 단일 실행(python)에서만 단일 GPU 강제 — 0.5B는 2-GPU DataParallel/auto-shard가 느림.
# torchrun(DDP)으로 띄우면 LOCAL_RANK가 설정되므로 건드리지 않음(각 프로세스가 자기 GPU 사용 → 진짜 병렬).
if os.environ.get("LOCAL_RANK") is None and os.environ.get("WORLD_SIZE") is None:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import argparse
import json
from pathlib import Path

import yaml

from _common import build_user_block


def load_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_chat_dataset(jsonl_path: str, tokenizer, system_prompt: str, max_len: int, supports_system: bool = True):
    """JSONL → chat-template 토크나이즈.

    중요: datasets.load_dataset("json", ...)이 ISO 8601 문자열을 pyarrow timestamp로
    자동 변환하고 UTC로 정규화해버려서 학습 데이터의 +09:00이 사라지는 버그가 있음
    (2026-05 v1 학습에서 time_match 0.34로 떨어진 원인).
    JSONL을 직접 파싱한 dict 리스트로 Dataset.from_list 하면 문자열 그대로 보존.
    """
    import orjson
    from datasets import Dataset

    rows = []
    with open(jsonl_path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(orjson.loads(line))
    raw = Dataset.from_list(rows)

    def to_chat(ex):
        user_block = build_user_block(ex)  # thread_context 있으면 <대화내역> 블록 자동 삽입
        gold_str = json.dumps(ex["gold"], ensure_ascii=False)
        if supports_system:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
                {"role": "assistant", "content": gold_str},
            ]
        else:
            # Gemma 등 system 역할 미지원 템플릿: system을 첫 user 턴 접두로 합침
            messages = [
                {"role": "user", "content": system_prompt + "\n\n" + user_block},
                {"role": "assistant", "content": gold_str},
            ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    return raw.map(to_chat, remove_columns=raw.column_names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    model_cfg = load_yaml(cfg["model_config"])
    lora_cfg = load_yaml(cfg["lora_config"])

    # 무거운 import는 여기서
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer, SFTConfig

    # 정밀도는 config 따름 (bf16). 큰 vocab(152k)에서 fp16은 softmax 정밀도 문제로 품질↓
    # (r7 fp16 회귀) → bf16 사용. T4에선 bf16이 에뮬레이션이라 느리지만 품질 우선.
    if torch.cuda.is_available():
        print(f"[train] GPU={torch.cuda.get_device_name(0)} cap={torch.cuda.get_device_capability()} "
              f"visible={torch.cuda.device_count()} → {'bf16' if cfg.get('bf16') else 'fp16'} (config)")
    # DDP면 유효배치 = per_device × world × accum 이 world배 커짐 → accum을 나눠 유효배치 유지
    _world = int(os.environ.get("WORLD_SIZE", 1))
    if _world > 1:
        _orig = cfg["gradient_accumulation_steps"]
        cfg["gradient_accumulation_steps"] = max(1, _orig // _world)
        print(f"[train] DDP world={_world}: grad_accum {_orig}→{cfg['gradient_accumulation_steps']} (유효배치 유지)")

    print(f"[train] 모델: {model_cfg['hf_id']}")
    tokenizer = AutoTokenizer.from_pretrained(model_cfg["hf_id"], trust_remote_code=model_cfg.get("trust_remote_code", False))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.model_max_length = model_cfg["max_seq_len"]

    bnb = None
    if cfg.get("load_in_4bit"):
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=cfg.get("bnb_4bit_quant_type", "nf4"),
            bnb_4bit_compute_dtype=getattr(torch, cfg.get("bnb_4bit_compute_dtype", "bfloat16")),
            bnb_4bit_use_double_quant=cfg.get("bnb_4bit_use_double_quant", True),
        )

    # stable-fp16: fp16 모드일 때 베이스를 fp32로 로드(=fp32 마스터 가중치) + 아래 fp16=True가
    # AMP autocast/GradScaler로 fp16 연산(T4 텐서코어, 빠름)을 함. 순수 fp16 로드(언더플로/불안정)
    # 대신 이 방식이 fp16 속도 + bf16급 안정성. (bf16 모드는 그대로 bf16 로드 — 범위 넓어 안전)
    load_dtype = torch.bfloat16 if cfg.get("bf16") else torch.float32
    _ddp = os.environ.get("LOCAL_RANK") is not None
    _hf_token = os.environ.get("HF_TOKEN") or None
    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["hf_id"],
        dtype=load_dtype,
        device_map=(None if _ddp else "auto"),
        trust_remote_code=model_cfg.get("trust_remote_code", False),
        quantization_config=bnb,
        token=_hf_token,
    )
    model.config.use_cache = False

    peft_cfg = LoraConfig(
        r=lora_cfg["r"],
        lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        bias=lora_cfg.get("bias", "none"),
        task_type=lora_cfg.get("task_type", "CAUSAL_LM"),
        target_modules=lora_cfg["target_modules"],
    )
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()

    _supports_system = model_cfg.get("supports_system", True)
    train_ds = build_chat_dataset(cfg["train_data"], tokenizer, model_cfg["system_prompt"], model_cfg["max_seq_len"], _supports_system)
    eval_ds = build_chat_dataset(cfg["eval_data"], tokenizer, model_cfg["system_prompt"], model_cfg["max_seq_len"], _supports_system)

    # trl이 버전에 따라 max_seq_length/max_length 인자명이 다름.
    # 모든 버전에서 통하는 경로: 토크나이저의 model_max_length 위에서 설정 + SFTConfig에는 미지정.
    sft_kwargs = dict(
        output_dir=cfg["output_dir"],
        run_name=cfg["run_name"],
        per_device_train_batch_size=cfg["per_device_train_batch_size"],
        per_device_eval_batch_size=cfg["per_device_eval_batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation_steps"],
        num_train_epochs=cfg["num_train_epochs"],
        learning_rate=cfg["learning_rate"],
        lr_scheduler_type=cfg["lr_scheduler_type"],
        warmup_ratio=cfg.get("warmup_ratio", 0.05),
        weight_decay=cfg["weight_decay"],
        max_grad_norm=cfg["max_grad_norm"],
        seed=cfg["seed"],
        logging_steps=cfg["logging_steps"],
        save_strategy=cfg["save_strategy"],
        save_total_limit=cfg["save_total_limit"],
        eval_strategy=cfg["eval_strategy"],
        load_best_model_at_end=cfg["load_best_model_at_end"],
        metric_for_best_model=cfg["metric_for_best_model"],
        greater_is_better=cfg["greater_is_better"],
        bf16=cfg["bf16"],
        fp16=cfg["fp16"],
        gradient_checkpointing=cfg["gradient_checkpointing"],
        gradient_checkpointing_kwargs={"use_reentrant": False},  # DDP+checkpointing 안정
        ddp_find_unused_parameters=False,                        # LoRA: 동결 베이스 → unused 아님
        optim=cfg["optim"],
        dataloader_num_workers=cfg["dataloader_num_workers"],
        report_to=cfg.get("report_to", "none"),
        dataset_text_field="text",
        packing=False,
    )
    # 가능하면 max_length(현행) 또는 max_seq_length(구버전)를 시도. 둘 다 안 받으면 토크나이저 기본 사용.
    import inspect
    sft_params = inspect.signature(SFTConfig.__init__).parameters
    if "max_length" in sft_params:
        sft_kwargs["max_length"] = model_cfg["max_seq_len"]
    elif "max_seq_length" in sft_params:
        sft_kwargs["max_seq_length"] = model_cfg["max_seq_len"]
    sft_cfg = SFTConfig(**sft_kwargs)

    # trl이 버전에 따라 tokenizer/processing_class 인자명이 다름.
    trainer_kwargs = dict(
        model=model,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        args=sft_cfg,
    )
    trainer_params = inspect.signature(SFTTrainer.__init__).parameters
    if "processing_class" in trainer_params:
        trainer_kwargs["processing_class"] = tokenizer
    elif "tokenizer" in trainer_params:
        trainer_kwargs["tokenizer"] = tokenizer

    # (선택) completion-only 손실: 프롬프트(system+user+assistant 헤더)는 마스킹하고
    # 응답 토큰(gold JSON + 종료토큰)에만 loss를 건다. packing=False(위에서 설정)일 때만 동작.
    _use_completion_only = cfg.get("completion_only_loss")
    _resp = model_cfg.get("response_template", "<|im_start|>assistant\n")

    _collator_set = False
    if _use_completion_only:
        _resp_ids = tokenizer.encode(_resp, add_special_tokens=False)
        # 방법 1: train_on_responses_only (trl >= 0.12 권장)
        # 방법 2: DataCollatorForCompletionOnlyLM (구버전 fallback)
        # 방법 3: 직접 찾기 (중간 버전 경로 편차 대응)
        _completion_fn = None
        try:
            from trl import train_on_responses_only as _completion_fn
        except ImportError:
            pass

        if _completion_fn is None:
            # DataCollatorForCompletionOnlyLM 경로 탐색
            import importlib
            for _mod in ("trl", "trl.trainer.utils", "trl.trainer", "trl.data_utils"):
                try:
                    _DC = getattr(importlib.import_module(_mod), "DataCollatorForCompletionOnlyLM")
                    trainer_kwargs["data_collator"] = _DC(response_template=_resp_ids, tokenizer=tokenizer)
                    print(f"[train] completion-only ON (DataCollatorForCompletionOnlyLM/{_mod}) template={_resp!r}")
                    _collator_set = True
                    break
                except (ImportError, AttributeError):
                    continue

    trainer = SFTTrainer(**trainer_kwargs)

    if _use_completion_only and not _collator_set:
        if _completion_fn is not None:
            try:
                trainer = _completion_fn(trainer, response_template=_resp)
                print(f"[train] completion-only ON (train_on_responses_only) template={_resp!r}")
                _collator_set = True
            except Exception as e:
                print(f"[train] WARNING: train_on_responses_only 실패({e}), 전체 토큰 학습으로 진행")
        else:
            print(f"[train] WARNING: completion-only 설정 불가(trl 버전 미지원), 전체 토큰 학습으로 진행")

    trainer.train()
    trainer.save_model(cfg["output_dir"])
    tokenizer.save_pretrained(cfg["output_dir"])
    print(f"[train] 완료 → {cfg['output_dir']}")


if __name__ == "__main__":
    main()
