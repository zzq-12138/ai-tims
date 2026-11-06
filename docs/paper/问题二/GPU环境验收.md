# GPU 环境验收（Qwen2.5-7B-Instruct LoRA）

> 用途：确认问题二主方案（LoRA 微调）在租用卡上真实可跑，并给出可外推的耗时/显存基线。
> 机器：RTX 4090 24G（AutoDL，`connect.westc.seetacloud.com:50774`），¥1.88/h。
> 全部大文件位于 `/root/autodl-tmp`（独立 50 G 数据盘）；系统盘 `/` 30 G 未写入任何模型/数据/checkpoint。
> **状态：已完成验收。** 依赖、权重完整性、bitsandbytes 4bit/8bit 真实加载、LoRA 四组配置的 5-step 真实训练均已实测；剩余未验证项见第九节。
> 实测原始日志：GPU 机 `/root/autodl-tmp/logs/final_master.log`（每组一行 `RESULT {...}` JSON）。

## 一、结论

| 项 | 结果（实测） |
|---|---|
| 环境体检 | 通过：驱动 570.124.04、CUDA 12.8、torch 2.8.0+cu128、算力 (8,9)、24564 MiB、25 核 |
| 依赖 | 可用栈：transformers **4.46.3** / peft 0.21.2 / accelerate 1.15.0 / datasets 3.6.0 / hub 0.36.2 / bitsandbytes 0.50.2 / torch 2.8.0+cu128 |
| 模型完整性 | 通过：4 分片齐全、`safetensors.safe_open` 解析 339 个张量、0 缺失、0 `.incomplete` |
| bnb 4bit | **可用**：加载 13.4 s，峰值 5.31 GB，生成 0.92 s |
| bnb 8bit | **可用**：加载 21.7 s，峰值 8.35 GB，生成 3.18 s |
| LoRA（bf16，gc 开） | 1024/b1、1024/b2、2048/b1 三组通过；2048/b2 OOM；不开 gc 的 1024/b1 也 OOM |
| 推荐配置 | `seq_len=1024 / batch=1 / grad_accum=8 / grad_ckpt=on`，collator 按批内最长动态 padding |
| 1000 条 × 3 epoch | 实测外推 **2.2 h**（真实长度动态 padding）～ **3.6 h**（定长 1024 最坏情况） |
| 重复权重 | 已清理，数据盘 **22 G → 15 G，回收约 7 G** |

## 二、环境体检（原文记录）

体检输出原样留存在 GPU 机 `/root/autodl-tmp/env_check.txt`，关键行：

```
NVIDIA-SMI 570.124.04   Driver Version: 570.124.04   CUDA Version: 12.8
GPU 0: NVIDIA GeForce RTX 4090   24564MiB

df -h（首次体检时）:
/                 30G   789M   30G   3%
/dev/md0          50G    40K   50G   1%   /root/autodl-tmp
/dev/shm          45G     0    45G   0%

python: /root/miniconda3/bin/python  Python 3.12.3
torch = 2.8.0+cu128 ; torch.version.cuda = 12.8
cuda.is_available = True ; device_count = 1 ; capability = (8, 9)
total_mem_GB = 23.53 ; sm_count = 128
```

## 三、依赖与版本坑

最终可用版本（本轮全部实测通过）：

| 包 | 版本 | 说明 |
|---|---|---|
| transformers | **4.46.3** | 从 5.22.1 降级，原因见坑 1 |
| peft | 0.21.2 | |
| accelerate | 1.15.0 | |
| datasets | **3.6.0** | 降 hub 后 5.1.0 导入失败，见坑 5 |
| huggingface_hub | 0.36.2 | 随 transformers 4.46.3 降级 |
| bitsandbytes | 0.50.2 | 4bit/8bit 均实测可用 |
| trl | 1.17.1 | **与本栈不兼容**（要求 transformers>=4.56.2、datasets>=4.7.0），本方案不使用 |
| modelscope | 1.40.2 | 模型下载来源 |
| torch | 2.8.0+cu128 | |

实测踩到的坑（均为真实报错，不是推测）：

1. **transformers 5.22.1 的 Qwen2 实现里没有梯度检查点的调用点。** `grep` 确认 `modeling_qwen2.py` 只有 `supports_gradient_checkpointing = True` 与 `self.gradient_checkpointing = False`，**没有 `_gradient_checkpointing_func` 调用**。因此 `gradient_checkpointing_enable()` 只置标志、显存完全不降，4090 上 `seq_len=1024` 必 OOM。**必须用 4.46.x**（4.46.3 已确认存在该调用点）。
2. **必须调用 `model.train()`。** Qwen2 的 checkpoint 分支是 `if self.gradient_checkpointing and self.training`，eval 态下 gc 永不生效。此前不开 `train()` 的所有 gc 结果全部无效。
3. **gc 必须在 `get_peft_model` 之后开启，且 `use_reentrant=False`**，并配合 `enable_input_require_grads()`；否则只有 adapter 需要梯度时反传出错/不省显存。
4. **不要用 `TrainingArguments(gradient_checkpointing=True)`**：Trainer 默认 `use_reentrant=True`，与 LoRA 不兼容。脚本改为手动开 gc、TrainingArguments 里置 False。
5. 降级 transformers 后 `import datasets` 报 `ImportError: cannot import name 'BucketNotFoundError' from 'huggingface_hub.errors'`（datasets 5.1.0 要求 hub>=1.31，而 hub 被降到 0.36.2）→ 装 `datasets==3.6.0` 后恢复。
6. transformers 5.x `TrainingArguments` 无 `warmup_ratio`（只有 `warmup_steps`）；精度参数 5.x 叫 `dtype`、4.x 叫 `torch_dtype`；`evaluation_strategy` 已改名 `eval_strategy`。脚本已做兼容。
7. `huggingface_hub 2.4` 默认走 Xet 后端，经 AutoDL 加速代理访问 `cas-server.xethub.hf.co` 返回 **401**；需 `export HF_HUB_DISABLE_XET=1`。

## 四、bitsandbytes 真实 4bit/8bit 冒烟

方法：真实 `from_pretrained` 加载 Qwen2.5-7B-Instruct，再做一次 `generate(max_new_tokens=24)`；不是只 import。原始输出：

```
RESULT {"mode":"4bit","ok":true,"load_s":13.4,"peak_load_GB":5.29,"gen_s":0.92,
        "gen_text":"贴片机抛料的三个常见原因是焊料不足、元器件放置不正确以及贴装头压力设置",
        "peak_total_GB":5.31}
RESULT {"mode":"8bit","ok":true,"load_s":21.7,"peak_load_GB":8.35,"gen_s":3.18,
        "gen_text":"贴片机抛料的三个常见原因是焊盘或元器件异常、贴装头压力设置不当以及PC",
        "peak_total_GB":8.35}
```

| 量化 | 加载 | 峰值显存 | 生成 24 token | 结论 |
|---|---|---|---|---|
| 4bit（nf4 + double quant + bf16 compute） | 13.4 s | 5.31 GB | 0.92 s | 可用 |
| 8bit | 21.7 s | 8.35 GB | 3.18 s | 可用 |

结论：bitsandbytes 0.50.2 + torch 2.8.0+cu128 **兼容可用**，无告警/无报错。但**训练侧不推荐 QLoRA**：实测 4bit 权重虽只有 7.35 GB，激活反而更大（见第五节 4bit 组全部 OOM），显存瓶颈在激活不在权重。4bit 只建议用于推理/评测。

## 五、LoRA 冒烟实测

方法：bf16 全量加载 + LoRA（r=16, α=32, target_modules=`q/k/v/o_proj` + `gate/up/down_proj`），trainable params = **40,370,176**（与理论值 28×1,441,792 精确一致）。每组独立进程，**真实 forward + backward + optimizer.step** 跑 5 步，`grad_accum` 记为 8；`pad=full` 表示每条补齐到恰好 `seq_len`（最坏情况）。单 step 耗时取第 2–5 步均值（去掉第 1 步 warmup）。

### 5.1 正式矩阵（transformers 4.46.3 + `model.train()` + gc）

| 配置 (seq/batch) | 单 step 秒 | 每个样本秒 | 显存峰值 alloc / reserved | OOM | 备注 |
|---|---|---|---|---|---|
| 1024 / 1 | **4.265** | 4.265 | **17.04 / 17.55 GB** | 否 | 可用 |
| 1024 / 2 | **8.690** | 4.345 | **19.89 / 20.53 GB** | 否 | 可用，但每样本更慢 |
| 2048 / 1 | **8.792** | 8.792 | **19.27 / 20.53 GB** | 否 | 可用，耗时翻倍 |
| 2048 / 2 | — | — | 21.47 GB（第 1 步） | **是** | `Tried to allocate 2.32 GiB`，仅剩 2.05 GiB |

附：`1024/1` 动态 padding（按批内最长，实测均值 248.8 token）= **2.325 s/step，峰值 15.38 GB**；同配置**不开 gc 直接 OOM**（`Tried to allocate 74.00 MiB`，已用 23.47 GiB）。

各组 loss（5 步）：2.05 → 1.62 → 1.25 → 0.99 → 0.73，链路正常。

### 5.2 失败对照（同一台机、同一脚本，换配置复现）

| 配置 | 结果 | 报错原文（截断） |
|---|---|---|
| 1024/1 无 gc | OOM | `CUDA out of memory. Tried to allocate 74.00 MiB ... 23.47 GiB in use` |
| 2048/2 + gc | OOM | `Tried to allocate 2.32 GiB ... 21.47 GiB in use` |
| 4bit QLoRA 896/1 | OOM | `Tried to allocate 520.00 MiB` |
| 4bit QLoRA 1024/1 | OOM | `Tried to allocate 112.00 MiB`（权重仅 7.35 GB，激活超限） |
| 768/1 无 gc（早期，修 gc 前） | OOM | `Tried to allocate 446.00 MiB` |

结论：**4090 24 G 上 bf16 + LoRA 必须开 gc**；开启后 `1024` 两档、`2048/b1` 均可跑，`2048/b2` 是硬上限。

## 六、1000 条 × 3 epoch 耗时外推

口径：总样本 `N = 1000 × 3 = 3000`。`grad_accum=8` 只改变优化器步频（b1 时 375 次 optimizer step），**不改变每个 micro-batch 的计算时间**，故：

```
T = t_step × (N / batch)
t_step 取第五节实测的「单 step 秒」（已扣除 warmup）
```

| 口径 | 公式 | 结果 |
|---|---|---|
| 定长 1024，batch=1（最坏情况） | 4.265 × 3000 | 12,795 s = **3.55 h** |
| 定长 1024，batch=2 | 8.690 × 1500 | 13,035 s = **3.62 h** |
| 定长 2048，batch=1 | 8.792 × 3000 | 26,376 s = **7.33 h** |
| 动态 padding（实测均值 248.8 tok），batch=1 | 2.325 × 3000 | 6,975 s = **1.94 h** |

真实数据不是 248.8 token，需按 token 长度分布换算。用两组实测点（248.8 tok → 2.325 s；1024 tok → 4.265 s）线性拟合单样本成本：

```
斜率 = (4.265 - 2.325) / (1024 - 248.8) = 0.002503 s/token
截距 = 2.325 - 0.002503 × 248.8       = 1.702 s
t(L) = 1.702 + 0.002503 × L
```

真实 1000 条（`docs/paper/问题二/annotation_set_v1.csv`）的 total token 分布：p50 297 / 均值 355.1 / p95 664 / max 714；>512 有 200 条、>640 有 88 条、>768 有 0 条。

```
T ≈ 3000 × t(355.1) = 3000 × (1.702 + 0.8886) = 7,773 s ≈ 2.16 h
```

假设与误差：① 拟合是线性的，attention 为超线性项，实际会略高于线性值；② 生产用 collator 按批内最长 padding，与动态单样本口径一致；③ 未计每 epoch 保存 adapter（<10 s）与一次模型加载（约 7 s）。

**排期取值：2.2 h（按真实长度）～ 3.6 h（定长 1024 保守上界），建议按 3 h 报排期。**

## 七、推荐配置

**`seq_len=1024 / batch=1 / grad_accum=8 / grad_ckpt=on` + 按批内最长动态 padding**（即 `train_lora.py` 当前默认）。

理由（全部基于上表实测）：

1. **gc 必须开**：不开时 1024/b1 直接 OOM，无可选项。
2. **seq_len=1024 足够**：真实数据最长 714 token，>768 为 0 条；2048 档耗时翻倍（8.792 s vs 4.265 s）且显存更高，无收益。
3. **batch=2 不划算**：1024/b2 每样本 4.345 s 反而慢于 b1 的 4.265 s，显存多 2.85 GB（reserved 20.53 GB，只剩 3 GB 余量）；2048/b2 直接 OOM。当前无证据支持 batch=2。
4. **显存余量**：b1/1024 峰值 17.04 GB（alloc）、17.55 GB（reserved），距 23.53 GB 有约 6 GB，够评测/长样本波动。
5. **grad_accum=8**：b1 下等效 batch 8，375 次 optimizer step/epoch 组合，配合 lr=2e-4 稳定。

可选：batch=2 + 动态 padding 未实测，若后续想再压时间，需单独跑 5 step 对照，不能直接假定更快。

## 八、机时与费用

| 时段 | 起止（CST） | 机时 | 费用（¥1.88/h） | 主要工作 |
|---|---|---|---|---|
| 第一次 | 2026-11-05 23:15 → 11-06 00:45 | 1.5 h | ¥2.82 | 体检、装依赖、下载模型、初步 OOM 排查 |
| 第二次 | 2026-11-06 09:20 → 10:20（实测结束） | 1.0 h | ¥1.88 | 权重清理、bnb 4/8bit、四组 LoRA 实测、落文档 |
| **合计** | | **约 2.5 h** | **约 ¥4.7** | |

> 机器当前仍开机。关机由用户决定；若继续挂机，按 ¥1.88/h 计。本轮已完成全部补测，建议测完即关机。

## 九、未验证项与局限

- **2048/b2 OOM**：是本卡显存硬上限，未做"降一档"以外的进一步优化（如 4bit + gc 组合、DeepSpeed ZeRO）。
- **batch=2 + 动态 padding 未测**：结论仅覆盖定长 padding 的 batch=2。
- **QLoRA 训练未通过**：4bit 权重 7.35 GB 但激活受限，896/1024 全 OOM；只验证了推理可用。
- **trl 1.17.1 不可用**：与降级后的栈版本冲突；本方案不使用。
- **多卡 / DeepSpeed / flash-attention 未测**：单卡单实例。
- **loss 只证明链路通**：冒烟用 8 条合成工单，loss 2.05→0.73 不代表收敛质量；真实数据训练效果需另做评测。
- **耗时外推是线性拟合**：长序列（>1024）会低估，故给了 3.6 h 保守上界。
- **网络**：HF 官方 + 代理 10–15 MB/s 但会断连（Xet 401）；ModelScope 8 并发 1.5–6 MB/s，为本次模型最终来源。

## 十、重复权重核查与清理（已完成）

清理前用户侧观测：数据盘 **22 G / 50 G**。核查命令与结果：

```bash
find /root/autodl-tmp/models -name "*.incomplete" -printf "%p %s\n"
# → 仅命中 models/Qwen2.5-7B-Instruct-hf 下的半成品分片

du -sh /root/autodl-tmp/models/* /root/autodl-tmp/hf
# → models/Qwen2.5-7B-Instruct     15G   （完整）
# → models/Qwen2.5-7B-Instruct-hf  ~6G   （HF 官方半成品，含 .incomplete）
# → /root/autodl-tmp/hf            ~1G   （HF_HOME 缓存）
```

删除前的安全闸（保留目录必须 4 个 `.safetensors` 且无 `.incomplete`）：

```bash
n=$(ls /root/autodl-tmp/models/Qwen2.5-7B-Instruct/*.safetensors | wc -l)   # → 4
inc=$(find /root/autodl-tmp/models/Qwen2.5-7B-Instruct -name "*.incomplete" | wc -l)  # → 0
# 两者均满足后才执行删除
rm -rf /root/autodl-tmp/models/Qwen2.5-7B-Instruct-hf /root/autodl-tmp/hf
```

清理后复核（当前状态）：

```
4                                   # 保留目录分片数
0                                   # 全盘 .incomplete 数
15G  /root/autodl-tmp/models/Qwen2.5-7B-Instruct
ls: cannot access '/root/autodl-tmp/hf': No such file or directory
ls: cannot access '/root/autodl-tmp/models/Qwen2.5-7B-Instruct-hf': No such file or directory
/dev/md0   50G   15G   36G   29%   /root/autodl-tmp
```

**回收量：22 G → 15 G，约 7 G。**

完整性校验（不是只看字节数）：用 `safetensors.safe_open` 逐分片解析 header，并以 `model.safetensors.index.json` 的 `weight_map` 校验 key 覆盖 → **339 个张量，0 缺失**。

> 更正：4 个分片文件字节和实测为 **15,231,271,888 B**，比 index 的 `metadata.total_size`（15,231,233,024 B）多 38,864 B。差值是 4 个 safetensors 文件头/对齐开销（每文件约 9.7 KB），**属正常现象**；此前文档写"完全一致"不准确。
