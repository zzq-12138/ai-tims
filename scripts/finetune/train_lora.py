#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen2.5-7B-Instruct LoRA 训练脚本（工单文本 → 五元组 JSON）。

设计取舍：
- 用 transformers `Trainer` + peft，避开 trl 1.x 的 SFTTrainer API 变更（当前 trl 1.17 已把
  `max_seq_length` 改成 `max_length`，不同小版本差异大），训练循环完全可控、易复现。
- prompt 段 label 置 -100，只在 JSON 答案上计 loss（避免模型学会复述问题）。
- 支持断点续训（`--resume` 读 `output_dir/checkpoint-*`）。
- 数据格式见同目录 `data_format.md`。

**版本要求（实测）**：必须 `transformers==4.46.x`。
transformers 5.22.1 的 Qwen2 实现里没有 `_gradient_checkpointing_func` 调用点，
`gradient_checkpointing_enable()` 只置标志、显存不降，导致 4090(24G) 上 seq_len≥768 必 OOM。

用法：
    python scripts/finetune/train_lora.py \
      --model_dir /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
      --train_file data/train.jsonl \
      --output_dir /root/autodl-tmp/ckpt/qwen25-7b-lora \
      --seq_len 1024 --batch_size 2 --grad_accum 4 --epochs 3 --grad_ckpt
"""
import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    set_seed,
)

SYSTEM_PROMPT = (
    "你是半导体封装测试设备的知识抽取助手。请从工单文本中抽取结构化知识，"
    "只输出一个 JSON 对象，不要输出解释、不要加代码块。字段必须齐全："
    "phenomenon（现象）、root_cause（根因）、measures（措施，字符串数组）、"
    "verification（验证结果）、applicable_conditions（适用条件对象：device/model/process/preconditions）、"
    "excluded_hypotheses（被排除的假设，数组，元素含 hypothesis/reason，可为空数组）。"
)

LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def _from_pretrained(model_dir: str, **kw):
    """兼容 transformers 4.x(torch_dtype) / 5.x(dtype)。"""
    try:
        return AutoModelForCausalLM.from_pretrained(
            model_dir, dtype=torch.bfloat16, trust_remote_code=True, **kw)
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(
            model_dir, torch_dtype=torch.bfloat16, trust_remote_code=True, **kw)


def build_messages(rec: dict) -> List[Dict[str, str]]:
    user = "工单文本：\n%s\n设备类型：%s\n设备型号：%s" % (
        rec["input"]["symptom_text"],
        rec.get("device_type", "未知"),
        rec["input"].get("device_model", "未知"),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def encode(rec: dict, tok, seq_len: int):
    """返回 input_ids / labels；prompt 段 label=-100。"""
    prompt_text = tok.apply_chat_template(build_messages(rec), tokenize=False, add_generation_prompt=True)
    answer_text = json.dumps(rec["output"], ensure_ascii=False, separators=(",", ":")) + tok.eos_token

    p_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    a_ids = tok(answer_text, add_special_tokens=False)["input_ids"]
    input_ids = (p_ids + a_ids)[:seq_len]
    labels = ([-100] * len(p_ids) + a_ids)[:seq_len]
    return {"input_ids": input_ids, "labels": labels}


@dataclass
class PadCollator:
    pad_id: int

    def __call__(self, feats):
        maxlen = max(len(f["input_ids"]) for f in feats)
        ids, labels, mask = [], [], []
        for f in feats:
            n = maxlen - len(f["input_ids"])
            ids.append(f["input_ids"] + [self.pad_id] * n)
            labels.append(f["labels"] + [-100] * n)
            mask.append([1] * len(f["input_ids"]) + [0] * n)
        return {
            "input_ids": torch.tensor(ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(mask, dtype=torch.long),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", required=True)
    ap.add_argument("--train_file", required=True, help="JSONL，每行一条 {id, device_type, input, output}")
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--seq_len", type=int, default=1024)
    ap.add_argument("--batch_size", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora_r", type=int, default=16)
    ap.add_argument("--lora_alpha", type=int, default=32)
    ap.add_argument("--lora_dropout", type=float, default=0.05)
    ap.add_argument("--grad_ckpt", action="store_true", help="开启梯度检查点（省显存，约慢 20-30%）")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max_samples", type=int, default=0, help=">0 时只取前 N 条（冒烟用）")
    args = ap.parse_args()

    set_seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(args.model_dir, trust_remote_code=True, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = _from_pretrained(args.model_dir, device_map={"": 0})
    model.config.use_cache = False

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=LORA_TARGETS,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    if args.grad_ckpt:
        # 必须在 peft 包装之后开启；use_reentrant=False 才与「只有 adapter 需要梯度」兼容。
        # 实测（4090 24G, bf16）：seq_len=1024 峰值 17.04 GB，seq_len=2048 峰值 19.27 GB。
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model.print_trainable_parameters()

    ds = load_dataset("json", data_files=args.train_file, split="train")
    if args.max_samples > 0:
        ds = ds.select(range(min(args.max_samples, len(ds))))

    def _map(rec):
        return encode(rec, tok, args.seq_len)

    ds = ds.map(_map, remove_columns=ds.column_names, desc="tokenize")

    targs = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=10,
        bf16=True,
        logging_steps=1,
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        dataloader_pin_memory=False,
        # 不交给 Trainer 开 gc：它会用默认 use_reentrant=True，与 LoRA 不兼容；已在上面手动开
        gradient_checkpointing=False,
        remove_unused_columns=False,
        seed=args.seed,
    )

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=ds,
        data_collator=PadCollator(tok.pad_token_id),
    )
    trainer.train(resume_from_checkpoint=args.resume or None)
    trainer.save_model(args.output_dir)          # 只保存 adapter（peft 模型）
    tok.save_pretrained(args.output_dir)
    print("[ok] adapter saved ->", args.output_dir)
    print("[mem] peak_allocated=%.2f GB  peak_reserved=%.2f GB" % (
        torch.cuda.max_memory_allocated() / 1024 ** 3,
        torch.cuda.max_memory_reserved() / 1024 ** 3,
    ))


if __name__ == "__main__":
    main()
