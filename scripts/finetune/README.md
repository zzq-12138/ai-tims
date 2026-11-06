# Qwen2.5-7B-Instruct LoRA 微调环境（RTX 4090 24G）

面向问题二（知识抽取 / 三关系判别 / 条件化）的 LoRA 训练环境说明与实测记录。
所有大文件都在数据盘 `/root/autodl-tmp`，系统盘 `/` 不写任何模型/数据/checkpoint。

## 1. 机器与驱动

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090，24564 MiB（实测可用 23.53 GB），算力 8.9，128 SM |
| CPU / 内存 | 25 核 / 754 GB |
| 系统盘 | `/` 30 G（已用约 851 M） |
| 数据盘 | `/root/autodl-tmp` 50 G（当前 15 G / 29%） |
| 驱动 / CUDA | 570.124.04 / 12.8 |
| Python | 3.12.3（`/root/miniconda3/bin/python`） |
| PyTorch | 2.8.0+cu128，`cuda.is_available=True` |
| 计费 | ¥1.88/h |

## 2. 必设环境变量（每个新 shell 都要先 export）

```bash
export HF_HOME=/root/autodl-tmp/hf
export HF_ENDPOINT=https://hf-mirror.com
```

> 实测下载渠道：hf-mirror 单连接 ~13 KB/s；ModelScope 8 并发 1.5–6 MB/s（**本次模型最终来源**）；
> 启用 AutoDL 加速（`source /etc/network_turbo`）后 HF 官方可达 10–15 MB/s，但会 `peer closed connection` 断连，
> 且 hub 2.4 的 Xet 后端经代理报 401，需 `export HF_HUB_DISABLE_XET=1`。
> 训练为离线加载本地目录，`HF_ENDPOINT` 仅作运行时兜底。

## 3. 依赖版本（已实测可用）

| 包 | 版本 | 说明 |
|---|---|---|
| transformers | **4.46.3** | 必须 4.46.x，原因见下 |
| peft | 0.21.2 | |
| accelerate | 1.15.0 | |
| datasets | **3.6.0** | 与 hub 0.36.2 配套 |
| huggingface_hub | 0.36.2 | 随 transformers 降级 |
| bitsandbytes | 0.50.2 | 4bit/8bit 推理均实测通过 |
| trl | 1.17.1 | **不兼容本栈**（需 transformers>=4.56.2），本方案不使用 |
| modelscope | 1.40.2 | 模型下载 |
| sentencepiece | 0.2.3 | |

### 版本坑（均已实测复现）

1. **transformers 5.x 对 Qwen2 的梯度检查点无效**：5.22.1 的 `modeling_qwen2.py` 里没有 `_gradient_checkpointing_func` 调用点，`gradient_checkpointing_enable()` 只置标志、显存不降，4090 上 `seq_len=1024` 必 OOM。**必须用 `transformers==4.46.x`**。
2. **必须 `model.train()`**：Qwen2 的 gc 分支是 `if self.gradient_checkpointing and self.training`，eval 态不生效。
3. **gc 要在 `get_peft_model` 之后开**，并传 `gradient_checkpointing_kwargs={"use_reentrant": False}` + `enable_input_require_grads()`。
4. **不要用 `TrainingArguments(gradient_checkpointing=True)`**：Trainer 默认 `use_reentrant=True`，与 LoRA 不兼容；脚本手动开 gc、该字段置 False。
5. **降级后需 `datasets==3.6.0`**：否则 `ImportError: cannot import name 'BucketNotFoundError' from 'huggingface_hub.errors'`。
6. transformers 5.x `TrainingArguments` 无 `warmup_ratio`（用 `warmup_steps`）；精度参数 5.x 为 `dtype`、4.x 为 `torch_dtype`；`eval_strategy` 替代 `evaluation_strategy`。脚本已兼容。
7. `huggingface_hub 2.4` 的 Xet 后端经 AutoDL 代理访问 `cas-server.xethub.hf.co` 返回 **401**，需 `HF_HUB_DISABLE_XET=1`。

## 4. 模型下载与完整性

```bash
python -m modelscope.cli.cli download --model Qwen/Qwen2.5-7B-Instruct \
  --local_dir /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
  --max-workers 8 --continue-on-error
```

校验：应见 4 个 `model-0000X-of-00004.safetensors`、`config.json`、`tokenizer*`、`generation_config.json`；`du -sh` 约 15 G。

本机校验结果：分片文件字节和 **15,231,271,888 B**，比 `model.safetensors.index.json` 的 `metadata.total_size`（15,231,233,024 B）多 38,864 B（4 个文件头/对齐开销，每文件约 9.7 KB，正常）。用 `safetensors.safe_open` 逐分片解析 + `weight_map` 校验 → **339 张量、0 缺失**。

重复副本已清理：`models/Qwen2.5-7B-Instruct-hf`（HF 半成品）与 `/root/autodl-tmp/hf` 缓存已删除，数据盘 22 G → 15 G，回收约 7 G。当前全盘 `.incomplete` 为 0。

## 5. 显存与吞吐实测

实测条件：bf16 全量加载 + LoRA（r=16/α=32，7 个投影层，trainable 40,370,176），真实 forward+backward+step，5 步取第 2–5 步均值；`pad=full` 为补齐到恰好 `seq_len`（最坏情况）。

| 配置 (seq/batch) | 单 step 秒 | 显存峰值 alloc / reserved | OOM |
|---|---|---|---|
| 1024 / 1 | 4.265 | 17.04 / 17.55 GB | 否 |
| 1024 / 2 | 8.690（每样本 4.345） | 19.89 / 20.53 GB | 否 |
| 2048 / 1 | 8.792 | 19.27 / 20.53 GB | 否 |
| 2048 / 2 | — | 21.47 GB | **是**（`Tried to allocate 2.32 GiB`） |
| 1024 / 1 动态 padding | 2.325 | 15.38 / 15.64 GB | 否 |
| 1024 / 1 不开 gc | — | 23.47 GB | **是**（`Tried to allocate 74.00 MiB`） |

**推荐：`seq_len=1024 / batch=1 / grad_accum=8 / --grad_ckpt`，collator 按批内最长动态 padding。**

- 真实数据最长 714 token、>768 为 0 条 → 1024 足够，2048 耗时翻倍无收益；
- batch=2 每样本反而更慢（4.345 vs 4.265 s）且多吃 2.85 GB，2048/b2 直接 OOM；
- b1/1024 reserved 17.55 GB，余约 6 GB 给评测与长度波动。

**1000 条 × 3 epoch 耗时**（按实测单 step 外推 `T = t_step × 3000 / batch`）：

| 口径 | 结果 |
|---|---|
| 定长 1024 / b1（保守上界） | 3.55 h |
| 定长 1024 / b2 | 3.62 h |
| 定长 2048 / b1 | 7.33 h |
| 动态 padding + 真实长度分布（拟合 `t(L)=1.702+0.002503·L`，均值 355 tok） | **约 2.2 h** |

排期建议按 **3 h** 报（上限 3.6 h）。拟合为线性，长序列会略低估，故保留保守上界。

bnb 推理实测：4bit 峰值 5.31 GB / 加载 13.4 s / 生成 0.92 s；8bit 峰值 8.35 GB / 21.7 s / 3.18 s。QLoRA **训练**不划算：4bit 权重仅 7.35 GB 但激活受限，896/1024 全 OOM。

## 6. 启动训练

```bash
export HF_HOME=/root/autodl-tmp/hf

python scripts/finetune/train_lora.py \
  --model_dir /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
  --train_file /root/autodl-tmp/data/train.jsonl \
  --output_dir /root/autodl-tmp/ckpt/qwen25-7b-lora \
  --seq_len 1024 --batch_size 1 --grad_accum 8 --epochs 3 --grad_ckpt
```

长任务必须脱离 SSH：

```bash
nohup python scripts/finetune/train_lora.py ... > /root/autodl-tmp/logs/train_$(date +%Y%m%d_%H%M).log 2>&1 &
```

断点续训：加 `--resume`（读 `output_dir/checkpoint-*`；`save_strategy=epoch`，`save_total_limit=2`）。

## 7. 失败对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `CUDA out of memory` at first step | 未开 gc，激活超 24 G | 必须 `transformers==4.46.3` + `model.train()` + peft 后开 gc（`use_reentrant=False`） |
| 开了 `--grad_ckpt` 显存不降 | transformers 5.x 无 gc 调用点；或模型仍在 eval 态 | 降 4.46.x 并确保 `model.train()` |
| 2048/b2 OOM（`Tried to allocate 2.32 GiB`） | 超过 24 G 硬上限 | 降到 2048/b1 或 1024/b2；不要硬扛 |
| 4bit QLoRA 896+ OOM | 权重降了但激活更大 | 训练用 bf16+gc；4bit 仅用于推理 |
| `ImportError: BucketNotFoundError` | datasets 5.1 与 hub 0.36 不匹配 | `pip install datasets==3.6.0` |
| `TypeError: unexpected keyword 'warmup_ratio'` | transformers 5.x 移除 | 用 `warmup_steps`（脚本已改） |
| `TypeError: unexpected keyword 'torch_dtype'` / `dtype` | 4.x vs 5.x 命名 | 脚本 try/except 兼容 |
| `bitsandbytes` 报 `libbitsandbytes_cuda...so` 缺失 | bnb 与 torch/CUDA 不匹配 | 本机 0.50.2 + torch 2.8.0+cu128 已实测可用 |
| 下载只有几十 KB/s | 走了 hf-mirror | 改用 `modelscope ... --max-workers 8` |
| 系统盘写满 | 缓存落到 `/root/.cache` | 确认 `HF_HOME` 已 export 到数据盘 |
| SSH 断开进程被杀 | 未脱离会话 | `nohup ... &` 或 `screen` |
