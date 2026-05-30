"""LoRA 학습 스크립트 (Qwen2.5-0.5B 또는 HyperCLOVA X SEED 0.5B).

사용:
    python scripts/train_lora.py --config configs/train.yaml

전제: pip install -e .[train]
"""
from __future__ import annotations

import os

# 단일 GPU 강제 (torch import 전에 설정해야 함). 0.5B는 2-GPU에서 device_map=auto가 모델을
# 분산 배치해 GPU간 통신으로 느려짐. 하드셋(Kaggle이 미리 0,1로 깔아둬도 1개만 보이게).
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import argparse
import json
from pathlib import Path

import yaml

from _common import build_user_block


def load_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_chat_dataset(jsonl_path: str, tokenizer, system_prompt: str, max_len: int):
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
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

    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["hf_id"],
        torch_dtype=torch.bfloat16 if cfg.get("bf16") else torch.float16,
        device_map="auto",
        trust_remote_code=model_cfg.get("trust_remote_code", False),
        quantization_config=bnb,
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

    train_ds = build_chat_dataset(cfg["train_data"], tokenizer, model_cfg["system_prompt"], model_cfg["max_seq_len"])
    eval_ds = build_chat_dataset(cfg["eval_data"], tokenizer, model_cfg["system_prompt"], model_cfg["max_seq_len"])

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
        warmup_ratio=cfg["warmup_ratio"],
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
    trainer = SFTTrainer(**trainer_kwargs)

    trainer.train()
    trainer.save_model(cfg["output_dir"])
    tokenizer.save_pretrained(cfg["output_dir"])
    print(f"[train] 완료 → {cfg['output_dir']}")


if __name__ == "__main__":
    main()
