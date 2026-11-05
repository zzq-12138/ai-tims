# Qwen2.5-7B-Instruct LoRA 微调环境（RTX 4090 24G）

面向问题二（知识抽取 / 三关系判别 / 条件化）的 LoRA 训练环境说明与实测记录。
所有大文件都在数据盘 `/root/autodl-tmp`，系统盘 `/` 不写任何模型/数据/checkpoint。

## 1. 机器与驱动

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090，24564 MiB（实测可用 23.53 GB），算力 8.9，128 SM |
| CPU / 内存 | 25 核 / 754 GB |
| 系统盘 | `/` 30 G（初始已用 789 M） |
| 数据盘 | `/root/autodl-tmp` 50 G（xfs，独立挂载） |
| 驱动 / CUDA | 570.124.04 / 12.8 |
| Python | 3.12.3（`/root/miniconda3/bin/python`） |
| PyTorch | 2.8.0+cu128，`cuda.is_available=True` |
| 计费 | ¥1.88/h |

## 2. 必设环境变量（每个新 shell 都要先 export）

```bash
export HF_HOME=/root/autodl-tmp/hf
export HF_ENDPOINT=https://hf-mirror.com
```

> 实测下载渠道对比：hf-mirror 单连接 ~13 KB/s；ModelScope 8 并发 1.5–6 MB/s（**本次模型的最终来源**）；
> 启用 AutoDL 加速（`source /etc/network_turbo`）后 HF 官方可达 10–15 MB/s，但会 `peer closed connection` 断连重试，
> 且 hub 2.4 的 Xet 后端经代理报 401，需 `export HF_HUB_DISABLE_XET=1`。
> 训练为离线加载本地目录，`HF_ENDPOINT` 仅作运行时兜底。

## 3. 依赖版本（已装进现有 conda 环境）

| 包 | 版本 |
|---|---|
| transformers | 5.22.1 |
| peft | 0.21.2 |
| accelerate | 1.15.0 |
| datasets | 5.1.0 |
| trl | 1.17.1 |
| bitsandbytes | 0.50.2 |
| modelscope | 1.40.2 |
| sentencepiece | 0.2.3 |

### 版本坑（实测踩到）

1. **transformers 5.x 的 `TrainingArguments` 没有 `warmup_ratio`**，只有 `warmup_steps`；写 `warmup_ratio=0.03` 会 `TypeError`。本脚本已改为 `warmup_steps=10`。
2. **trl 1.x 的 `SFTConfig` 用 `max_length`**（不再有 `max_seq_length`），且不同小版本参数漂移大 → 本方案不用 `SFTTrainer`，改用 `Trainer` + 自定义 Collator，行为可控。
3. **`from_pretrained` 的精度参数在 5.x 叫 `dtype`**，4.x 叫 `torch_dtype`；脚本里做了 try/except 自动兼容。
4. **`TrainingArguments` 的评估字段是 `eval_strategy`**（`evaluation_strategy` 已移除）。
5. **bitsandbytes 0.50.2 + torch 2.8.0+cu128：待验证**。已安装并记录版本，但真实 4bit/8bit 加载与生成冒烟**尚未执行**（实例被关机），不能宣称兼容，待 `bnb_smoke.py` 跑完回填。

## 4. 模型下载

```bash
python -m modelscope.cli.cli download --model Qwen/Qwen2.5-7B-Instruct \
  --local_dir /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
  --max-workers 8 --continue-on-error
```

校验：`ls` 应见 4 个 `model-0000X-of-00004.safetensors`、`config.json`、`tokenizer*`、`generation_config.json`；`du -sh` 约 15 G。

本机实测完整性校验通过：4 分片字节数 3,945,441,440 + 3,864,726,352 + 3,864,726,424 + 3,556,377,672 = **15,231,233,024**，与 `model.safetensors.index.json` 的 `metadata.total_size` 完全一致。

**重复副本需清理**：另起的一路 HF 官方下载落在 `models/Qwen2.5-7B-Instruct-hf`（未完成），加上 `HF_HOME=/root/autodl-tmp/hf` 缓存，可能占用 8–10 G。开机后先核查再删：

```bash
find /root/autodl-tmp/models -name "*.incomplete" -printf "%p %s\n"
du -sh /root/autodl-tmp/models/* /root/autodl-tmp/hf 2>/dev/null
# 确认完整目录无 .incomplete 后：
rm -rf /root/autodl-tmp/models/Qwen2.5-7B-Instruct-hf /root/autodl-tmp/hf
```

## 5. 显存与吞吐实测

**待验证（GPU 冒烟未执行，实例关机）。** 详见 `docs/paper/问题二/GPU环境验收.md`。目前只能给出候选配置，不能给出实测数字：

- bf16 + LoRA（r=16/α=32，7 个投影层）的可行性：待 `smoke_lora.py` 验证；
- 候选 `batch=1 / grad_accum=8 / seq_len=1024`（显存充裕时）；
- 候选 `batch=2 / grad_accum=4 / seq_len=2048`（长工单覆盖更好）；
- 显存吃紧时加 `--grad_ckpt`，或改 4bit QLoRA。

## 6. 启动训练

```bash
export HF_HOME=/root/autodl-tmp/hf

python scripts/finetune/train_lora.py \
  --model_dir /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
  --train_file /root/autodl-tmp/data/train.jsonl \
  --output_dir /root/autodl-tmp/ckpt/qwen25-7b-lora \
  --seq_len 1024 --batch_size 1 --grad_accum 8 --epochs 3
```

长任务必须脱离 SSH：

```bash
nohup python scripts/finetune/train_lora.py ... > /root/autodl-tmp/logs/train_$(date +%Y%m%d_%H%M).log 2>&1 &
```

断点续训：加 `--resume`（读 `output_dir/checkpoint-*`；`save_strategy=epoch`，`save_total_limit=2`）。

## 7. 失败对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `CUDA out of memory` at first step | 权重 14 G + 激活超 24 G | 降 `--seq_len` 或开 `--grad_ckpt`；或改 4bit QLoRA |
| `TypeError: unexpected keyword 'warmup_ratio'` | transformers 5.x 移除该字段 | 用 `warmup_steps` |
| `TypeError: unexpected keyword 'torch_dtype'` / `dtype` | 4.x vs 5.x 命名 | 脚本已自动兼容 |
| `bitsandbytes` 报 `libbitsandbytes_cuda...so` 缺失 | bnb 与 torch/CUDA 不匹配 | 升级 `bitsandbytes>=0.45`，或改用 bf16（本机无需量化） |
| 下载只有几十 KB/s | 走了 hf-mirror | 改用 `modelscope ... --max-workers 8` |
| 系统盘写满 | 缓存落到 `/root/.cache` | 确认 `HF_HOME` 已 export 到数据盘 |
| SSH 断开进程被杀 | 未脱离会话 | `nohup ... &` 或 `screen` |
