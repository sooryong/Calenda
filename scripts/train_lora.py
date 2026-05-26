"""LoRA 학습 스크립트 (Qwen2.5-0.5B 또는 HyperCLOVA X SEED 0.5B).

사용:
    python scripts/train_lora.py --config configs/train.yaml

전제: pip install -e .[train]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml


def load_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_chat_dataset(jsonl_path: str, tokenizer, system_prompt: str, max_len: int):
    """JSONL → chat-template 토크나이즈."""
    from datasets import load_dataset

    raw = load_dataset("json", data_files=jsonl_path, split="train")

    def to_chat(ex):
        user_block = (
            f"<채널: {ex['channel']}>\n"
            f"<수신시각: {ex['received_at']}>\n"
            f"<발신자: {ex.get('sender', '')}>\n"
            f"<메시지>\n{ex['message']}\n</메시지>"
        )
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

    print(f"[train] 모델: {model_cfg['hf_id']}")
    tokenizer = AutoTokenizer.from_pretrained(model_cfg["hf_id"], trust_remote_code=model_cfg.get("trust_remote_code", False))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

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

    sft_cfg = SFTConfig(
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
        max_seq_length=model_cfg["max_seq_len"],
        dataset_text_field="text",
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        args=sft_cfg,
        tokenizer=tokenizer,
    )

    trainer.train()
    trainer.save_model(cfg["output_dir"])
    tokenizer.save_pretrained(cfg["output_dir"])
    print(f"[train] 완료 → {cfg['output_dir']}")


if __name__ == "__main__":
    main()
