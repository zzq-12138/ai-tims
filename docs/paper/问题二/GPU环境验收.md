# GPU 环境验收（Qwen2.5-7B-Instruct LoRA）— 部分验收

> 用途：确认问题二主方案（LoRA 微调）在租用卡上真实可跑，并给出可外推的耗时/显存基线。
> 机器：RTX 4090 24G（AutoDL，`connect.westc.seetacloud.com:50774`），¥1.88/h。
> 全部大文件位于 `/root/autodl-tmp`（独立 50 G 数据盘）；系统盘 `/` 30 G 未写入任何模型/数据/checkpoint。
> **状态：环境与权重已就绪；GPU 冒烟（bnb 加载、LoRA 前向/反向、显存与耗时实测）因实例关机，未执行，待开机补测。**

## 一、结论（截至 2026-11-06 00:45 CST）

已完成（均为实测/校验值，非推算）：

| 项 | 结果 |
|---|---|
| 环境体检 | 通过：驱动 570.124.04、CUDA 12.8、torch 2.8.0+cu128、`cuda.is_available=True`、算力 (8,9)、显存 24564 MiB、25 核 |
| 依赖安装 | 通过：transformers 5.22.1 / peft 0.21.2 / trl 1.17.1 / accelerate 1.15.0 / datasets 5.1.0 / bitsandbytes 0.50.2 / modelscope 1.40.2 |
| 模型完整性 | 通过：4 个 `.safetensors` 分片齐全，合计 15,231,233,024 B，与 `model.safetensors.index.json` 的 `metadata.total_size` 完全一致 |
| 磁盘 | 数据盘 20 G / 50 G（含一份需清理的 HF 半成品副本，见第十节） |

未完成（**不得当作实测数字使用**）：

| 项 | 状态 | 补测方式 |
|---|---|---|
| bitsandbytes 真实 4bit/8bit 加载 + 生成 | **未执行** | `python /root/bnb_smoke.py`（已上传，含原始错误打印） |
| LoRA 冒烟（5 step forward+backward+step） | **未执行** | `bash /root/run_smoke.sh` |
| 单 step 耗时 / 显存峰值 / 是否 OOM | **未测** | 同上，脚本输出 `RESULT {...}` JSON |
| batch=2/4、seq_len=2048 组合探测 | **未执行** | 同上（脚本已内置四组配置） |
| 1000 条 × 3 epoch 实际耗时 | **未推算**（无实测 step 时间，不做理论外推） | 冒烟跑完后按 `per_sample_s` 外推 |

预计补测开销：bnb 冒烟约 5–8 min，LoRA 四组配置约 15–25 min（含 4 次模型加载），合计 **约 30 min / ¥1** 以内。明早开机后可直接跑，无需重新下载。

## 二、环境体检（原文记录）

体检输出原样留存在 GPU 机 `/root/autodl-tmp/env_check.txt`，以下为关键行：

```
NVIDIA-SMI 570.124.04   Driver Version: 570.124.04   CUDA Version: 12.8
GPU 0: NVIDIA GeForce RTX 4090   24564MiB  (P8, 30W)

容器 free -g 显示宿主视角 total 754 G（售卖规格为 25 核 / 90 G 内存，实际可用以 90 G 为准）

df -h（开始前）:
/                 30G   789M   30G   3%
/dev/md0          50G    40K   50G   1%   /root/autodl-tmp
/dev/shm          45G     0    45G   0%

python:
/root/miniconda3/bin/python  Python 3.12.3
pip 26.3

torch:
torch = 2.8.0+cu128
torch.version.cuda = 12.8
cuda.is_available = True
device_count = 1
name = NVIDIA GeForce RTX 4090
capability = (8, 9)
total_mem_GB = 23.53
sm_count = 128
```

## 三、依赖与版本坑

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
| torch | 2.8.0+cu128 |

实测踩到的坑（均为写脚本时的真实报错，不是推测）：

1. `transformers 5.x TrainingArguments` **没有 `warmup_ratio`**，只有 `warmup_steps`；`warmup_ratio=0.03` 直接 `TypeError`。
2. `trl 1.x SFTConfig` 用 `max_length`（不是 `max_seq_length`）；为避免小版本漂移，训练脚本改用 `Trainer` + 自定义 Collator。
3. `from_pretrained` 精度参数 5.x 为 `dtype`、4.x 为 `torch_dtype`；脚本用 try/except 兼容。
4. `evaluation_strategy` 已移除，改为 `eval_strategy`。
5. `huggingface_hub 2.4.0` 默认走 Xet 存储后端，经 AutoDL 加速代理访问 `cas-server.xethub.hf.co` 返回 **401 Unauthorized**；必须 `export HF_HUB_DISABLE_XET=1` 才回退到普通 HTTP 下载。
6. bitsandbytes 0.50.2 与 torch 2.8.0+cu128 的兼容性：**尚未做真实加载验证**（见第四节），目前仅有版本号记录，不能宣称已通过。

## 四、bitsandbytes 真实 4bit/8bit 冒烟

**未执行（实例关机）。** 待补测，脚本已就绪 `bnb_smoke.py`：4bit(nf4 + double quant + bf16 compute) 与 8bit 各做一次「加载 + `generate(max_new_tokens=24)`」，并打印 `RESULT` / `SUMMARY`（含 `load_s`、`peak_GB`、生成文本、原始错误 `type: msg`）。

补测命令：

```bash
bash -lc 'export MODEL_DIR=/root/autodl-tmp/models/Qwen2.5-7B-Instruct; python /root/bnb_smoke.py'
```

## 五、LoRA 冒烟实测

**未执行（实例关机）。** 脚本 `smoke_lora.py` 已就绪：bf16 全量加载 + LoRA(r=16, α=32, 7 个投影层)，8 条合成工单 → 五元组 JSON，配置矩阵 b1_s1024 / b2_s1024 / b4_s1024 / b2_s2048，每组记录 `step_times_s`、`losses`、`peak_alloc_GB`、`peak_reserved_GB`、`oom`。

补测命令：

```bash
bash -lc 'bash /root/run_smoke.sh'
```

## 六、耗时推算（1000 条 × 3 epoch）

**未推算。** 只有拿到 `b1_s1024` 的实测 `per_sample_s` 才能外推；目前无实测值，按约束不做理论估算。冒烟完成后按下面口径计算并回填本节：

```
总样本 = 1000 × 3 = 3000
预计训练秒数 = per_sample_s × 3000
预计分钟 = 预计训练秒数 / 60
（另加：模型加载约 1 次 ~1 min；每 epoch 保存 adapter <10 s）
```

## 七、推荐配置

**待实测确认。** 候选（开机后按冒烟结果二选一）：

- 若 b1_s1024 峰值显存 < 20 GB：推荐 `batch=1 / grad_accum=8 / seq_len=1024`，不开 grad ckpt；
- 若 b2_s2048 不 OOM 且吞吐更高：推荐 `batch=2 / grad_accum=4 / seq_len=2048`（覆盖长工单更完整）；
- 显存吃紧时：加 `--grad_ckpt`（约慢 20–30%）或改 4bit QLoRA。

## 八、机时与费用

| 项 | 值 |
|---|---|
| 开始 | 2026-11-05 23:30 (CST) |
| 结束（用户关机） | 2026-11-06 约 00:45 (CST) |
| 机时 | 约 1.25 h |
| 费用（¥1.88/h） | 约 ¥2.35 |
| 补测预计 | 约 0.5 h / 约 ¥1 |
| 关机 | 已由用户关机；明早开机补测后建议再关 |

## 九、局限

- 单卡单实例、无并发；未测多卡/DeepSpeed。
- 冒烟数据为 8 条合成工单（非真实标注），loss 下降只能证明链路通，不代表收敛质量。
- 显存峰值 `max_memory_allocated` 不含分配器缓存外碎片，需同时看 `max_memory_reserved`。
- 本节所有 GPU 数字缺失，待补测回填；**任何下游排期请以开机后的实测为准。**
- 网络下载受代理稳定性影响：HF 官方 + AutoDL 加速代理峰值 10–15 MB/s，但会出现 `peer closed connection` 断连重试；ModelScope 8 并发稳定在 1.5–6 MB/s。

## 十、重复权重核查（待开机核查）

本次为绕开 ModelScope 降速，另起了一路 HF 官方 + 代理下载到 **另一个目录**；该路未完成（7.6 G/15.2 G，且代理断连）。因此数据盘上可能存在两份：

| 路径 | 内容 | 处置建议 |
|---|---|---|
| `/root/autodl-tmp/models/Qwen2.5-7B-Instruct` | ModelScope 下载，**完整**（4 分片，15,231,233,024 B，与 index 一致） | **保留**，训练统一用这个 |
| `/root/autodl-tmp/models/Qwen2.5-7B-Instruct-hf` | HF 官方下载，**未完成**（含 `.incomplete`） | **删除** |
| `/root/autodl-tmp/hf` | `HF_HOME` 缓存（下载过程中的临时/元数据） | 删除（训练离线加载本地目录，不需要它） |

开机后先核查再删（确认完整目录无 `.incomplete` 后再动手）：

```bash
# 1) 核查：完整目录必须 4 个 .safetensors 且无 .incomplete
ls -la /root/autodl-tmp/models/Qwen2.5-7B-Instruct/
find /root/autodl-tmp/models -name "*.incomplete" -printf "%p %s\n"
du -sh /root/autodl-tmp/models/* /root/autodl-tmp/hf 2>/dev/null

# 2) 确认无误后清理半成品与缓存（回收约 8–10 G）
rm -rf /root/autodl-tmp/models/Qwen2.5-7B-Instruct-hf
rm -rf /root/autodl-tmp/hf
df -h /root/autodl-tmp | tail -1
```
