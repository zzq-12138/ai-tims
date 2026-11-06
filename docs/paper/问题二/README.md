# 问题二标注数据（合成语料）

> 本目录数据**全部由脚本合成**，不含任何真实企业工单、客户信息或产线数据。论文中须写「合成语料 / 模拟工单」，不得写「真实企业工单验证」。

- 生成日期：2026-11-06
- 对应文档：`docs/paper/研究方向/技术路线四步_v2_问题二.md` §3.1、`docs/paper/研究方向/标注手册_v1.md` §9
- 生成脚本：`scripts/annotation/gen_seed_1000.py`、`gen_relation_pairs.py`

## 文件

| 文件 | 说明 |
|---|---|
| `annotation_set_v1.csv` | 1000 条工单。前 5 列为原文与元信息，其余为**空标签列**，人工填写 |
| `_gold_draft.jsonl` | 生成真值（结构 / 风格 / 根因 / 排除假设）。**标注时不要打开**，只用于 κ 与错误分析 |
| `annotation_data.js` | 工作台自动加载（`window.ANNOTATION_DATA`），不含真值 |
| `annotation_workbench.html` | 单文件标注工作台，Chrome/Edge 双击打开 |
| `annotation_relation_v1.csv` | 300 对关系集，`relation` 列空 |
| `_gold_relation_draft.jsonl` | 关系真值，标注时不要打开 |
| `_dataset_stats.json` | 1000 条分层统计 |
| `_relation_stats.json` | 四类关系的 BGE-M3 相似度分布与 conflict 落点 |
| `s1_suggestions.jsonl` | 可选：S1 零样本参考值（默认开关关闭） |

## 1000 条分层（实测）

| 维度 | 分布 |
|---|---|
| 设备 | 贴片机 / AOI检测机 / 涂布机 / 贴合机 / 蚀刻机 各 **200** |
| 风格 | formal / colloquial / missing / typo / long 各 **200** |
| 结构 | 正常单因 **600** · 含排除假设 **300** · 仅排除无根因 **100** |
| 长文本 | **200** 条 >500 字（最长 776，最短 97，均值 306） |

## 300 对关系集（BGE-M3 实测）

| 关系 | 条数 | 相似度 min / p25 / median / p75 / max | 构造方式 |
|---|---|---|---|
| duplicate | 90 | 0.963 / 0.987 / 0.991 / 0.994 / 1.000（抽 30 对） | 同条知识换词 + 段序调整 + 标题前缀污染 |
| variant | 90 | 0.795 / 0.823 / 0.845 / 0.861 / 0.920（抽 30 对） | 同设备同故障族，换根因/措施/条件 |
| conflict | 80 | **0.894 / 0.917 / 0.932 / 0.942 / 0.950** | 同现象 + 不同根因，共享 0–2 句上下文 |
| unrelated | 40 | 0.497 / 0.545 / 0.591 / 0.634 / 0.675（抽 30 对） | 跨设备跨工序 |

- conflict 候选池 1350 条 → 字符 n-gram 粗排保留 400 条 → BGE 精算，**80/80 全部落在 0.85–0.95**，无需区间外补足；每类设备各 16 对。
- 粗排的意义：直接在 CPU 上精算 1350 条要编码 1500+ 条文本（约 15 分钟），粗排后只编码 454 条（约 5 分钟）。
- variant 的上尾（0.92）与 conflict 下尾（0.89）有重叠，说明**单靠相似度分不开「变体」与「冲突」**，这正是需要人工标 `condition_overlap` 的原因。

## 校准包与外行复核（今天就能用）

| 文件 | 给谁 | 说明 |
|---|---|---|
| `校准包_30条.md` | 标注者本人 | 30 条（10 含排除 / 10 正常 / 5 仅排除无根因 / 3 长文本 / 1 缺字段 / 1 错别字），只给 id + 摘要 + 分层类型，**不含答案** |
| `外行复核表_C30.md` | 外行复核人 | 30 条完整原文 + 3 道是/否/不确定题，可直接打印打勾 |
| `外行复核表_C30.csv` | 外行复核人 | 同上，Excel / 记事本填写；三个答案列留空 |
| `annotation_set_v1.csv` 的 `calib_batch` 列 | 工作台 | 这 30 条标 `C30`，工作台勾「仅显示 C30」即只看这 30 条 |

```bash
# 重新生成校准包（会同时刷新 calib_batch 列与 annotation_data.js）
python3 scripts/annotation/make_calib_package.py --seed 20261106

# 外行复核 → 两个二值字段的一致性（不是你全槽位标注的 κ）
python3 scripts/annotation/compute_kappa.py --mode layperson \
  --a annot_extract_user.jsonl \
  --b docs/paper/问题二/外行复核表_C30.csv \
  --gold docs/paper/问题二/_gold_draft.jsonl \
  --out docs/paper/问题二/kappa_layperson_C30.md
```

外行复核只覆盖「是否含排除假设」「有无最终根因」两个二值字段，**论文中不得表述为全量双人标注**，详见手册 §10。

## 重新生成

```bash
python3 scripts/annotation/gen_seed_1000.py --seed 20261106
# 可加 --with-s1 --s1-limit 200 生成零样本参考值（需 ZHIPU_API_KEY）

/home/dev/venvs/bge/bin/python scripts/annotation/gen_relation_pairs.py   # 需 BGE-M3
python3 scripts/annotation/gen_relation_pairs.py --embed hash              # 无依赖近似
```

生成是确定性的（固定 seed），重跑会覆盖同名文件。

## 标注 → κ

```bash
python3 scripts/annotation/compute_kappa.py \
  --a annot_extract_user.jsonl --b annot_extract_b.jsonl \
  --data docs/paper/问题二/annotation_set_v1.csv \
  --meta docs/paper/问题二/_gold_draft.jsonl \
  --out docs/paper/问题二/kappa_report.md
```

## 已知局限

1. 文本由模板 + 同义替换 + 噪声生成，句式多样性低于真实工单；已用 5 种风格缓解，但**不能替代真实数据**。
2. 现象描述的真实性由人工在标注时把关（发现与设备原理不符即标 `uncertain=1`）。
3. 知识库反推样本仅作补充（<15%），避免「库里有答案」的检索天花板偏差。
4. 关系集相似度用 BGE-M3 CPU 实测；生产检索用的是 embedding-3，落点会有差异，论文报告时须注明模型。
