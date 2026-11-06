# 问题二标注数据（合成语料）

> 本目录数据**全部由脚本合成**，不含任何真实企业工单、客户信息或产线数据。论文中须写「合成语料 / 模拟工单」，不得写「真实企业工单验证」。

- 生成日期：2026-11-06
- 对应文档：`docs/paper/研究方向/技术路线四步_v2_问题二.md` §3.1、`docs/paper/研究方向/标注手册_v1.md` §9、`标注方案变更说明.md`
- 生成脚本：`scripts/annotation/gen_seed_1000.py`、`gen_relation_pairs.py`、`gen_heldout_cross_template.py`

## 现行方案（2026-11-06 起）

人工标注方案已停用。真值在生成时就已确定，属于 **construction-based gold（弱监督）**，不是人工标注。三层核验：

| 层 | 做什么 | 产物 | 状态 |
|---|---|---|---|
| L1 自动核验 | 5 项可程序判定的自洽性检查 | `构造真值自检报告.md` | 五项 100% |
| L2 独立模型盲评 | glm-4-flash 按手册规则独立抽取，与构造真值比对 | `blind_predictions.jsonl`、`盲评一致性报告.md` | 见报告 |
| L3 极小人工抽检 | 10 条只答两个是非题，估计生成器保真度 | `人工抽检_10条.md` | **5/10 像、根因 0/10 明显写错 → 保真度一般**（仅对 v1 文本有效） |

### 文本版本口径（v1 / v2）

| 版本 | 文本 | 槽位真值 | 盲评产物 |
|---|---|---|---|
| **v1** | 口语化模板含 `又闹脾气了` 套话 | 构造真值 | `blind_predictions.jsonl`、`盲评一致性报告.md` |
| **v2** | 仅把 `又闹脾气了`/`这才算完事`/`先这么跑着` 替换为自然表述（200 条正文） | **逐字未变**（`_gold_draft.jsonl` md5 一致） | `blind_predictions_v2.jsonl`、`盲评一致性报告_修复后.md` |

> v2 只改措辞，不改任何槽位与真值，因此「真值自洽」「跨模板留出集」「KB」类结论不受影响；
> **盲评一致率以 v2 为准，v1 数字保留作历史基线并列呈现**。
> 人工抽检口径链：v1 5/10 → 替换套话 → **v2 待用户复核**（`人工抽检_10条_修复后.md`）；
> v2 结果回来前不得声称提升。

跨模板留出集（只测试、不进训练）：`heldout_cross_template.csv` + `_heldout_gold_draft.jsonl`。

> 禁止表述：「人工标注」「专家标注」「双人标注」「标注者间 κ」。正确表述：「构造真值」「弱监督标签」「构造真值与独立模型判定的一致性」。

## 文件

| 文件 | 说明 |
|---|---|
| `annotation_set_v1.csv` | 1000 条工单。前 5 列为原文与元信息，其余为空标签列（现行方案不再人工填写，仅保留 schema） |
| `_gold_draft.jsonl` | 构造真值（生成时确定）。盲评时模型不得接触 |
| `constructed_gold.jsonl` / `constructed_gold_alpaca.json` | 导出为训练/评测标准格式的真值（1000 条），schema 与被测模型输出一致 |
| `构造真值自检报告.md` | L1 自动核验报告（5 项） |
| `blind_predictions.jsonl` / `盲评一致性报告.md` | L2 盲评原始输出与一致性/κ 报告（**v1 文本口径**） |
| `blind_predictions_v2.jsonl` / `盲评一致性报告_修复后.md` | L2 盲评（**v2 文本口径**，替换文案腔后重跑） |
| `人工抽检_10条.md` | L3 保真度抽检表与回填结论（5/10 像真实报修，仅对 v1 文本有效） |
| `heldout_cross_template.csv` / `_heldout_gold_draft.jsonl` / `_heldout_stats.json` | 跨模板留出集 200 条（只测试，不进训练） |
| `标注方案变更说明.md` | 方案变更原因、三层结构与论文写法 |
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
- variant 的上尾（0.92）与 conflict 下尾（0.89）有重叠，说明**单靠相似度分不开「变体」与「冲突」**，这正是必须引入 `condition_overlap` 判定的原因。
- 关系真值同样由构造确定（`_gold_relation_draft.jsonl`），不做人工标注；一致性同样按「构造真值 vs 独立模型判定」口径报告。

## 校准包与外行复核（**已停用**）

| 文件 | 状态 | 说明 |
|---|---|---|
| `校准包_30条.md` | 已停用 | 30 条校准包，原用于人工标注前校准口径 |
| `外行复核表_C30.md` / `外行复核表_C30.csv` | 已停用 | 原用于外行复核两个二值字段 |
| `annotation_set_v1.csv` 的 `calib_batch` 列 | 保留 | 仍标 `C30`，工作台可按此过滤，仅供回溯 |
| `compute_kappa.py --mode layperson` | 已停用 | 无第二读者，不再使用 |

**停用原因**：1000 条 × 每条 1–2 分钟对非专业者是硬门槛，实测确认无法完成，也不再找第二人做 κ。
文件保留不删，便于答辩时说明「曾设计过、因成本不可行而停用」。详见 `标注方案变更说明.md`。

## 真值导出与三层核验

```bash
# L1 真值导出 + 自动核验
python3 scripts/annotation/export_constructed_gold.py
python3 scripts/annotation/verify_gold.py

# L2 独立模型盲评（glm-4-flash，不接触构造真值）
python3 scripts/annotation/blind_eval.py run --workers 14
python3 scripts/annotation/blind_eval.py compare

# L3 人工抽检：打开 人工抽检_10条.md，勾 10 组是非题
```

## 跨模板留出集

```bash
python3 scripts/annotation/gen_heldout_cross_template.py --n 200 --seed 20261107
```

- 模板族：`dispatch` / `wechat` / `logbook`（与训练集 5 种模板不重叠）
- 种子：20261107（训练集 20261106）；上下文索引偏移 137
- 分层：5 设备 × 40；normal 120 / excluded 60 / no_final 20
- 用途：只测试、不进训练；若跨模板性能显著下降，须在论文如实报告

## 重新生成

```bash
python3 scripts/annotation/gen_seed_1000.py --seed 20261106
# 可加 --with-s1 --s1-limit 200 生成零样本参考值（需 ZHIPU_API_KEY）

/home/dev/venvs/bge/bin/python scripts/annotation/gen_relation_pairs.py   # 需 BGE-M3
python3 scripts/annotation/gen_relation_pairs.py --embed hash              # 无依赖近似
```

生成是确定性的（固定 seed），重跑会覆盖同名文件。

## 已知局限

1. 文本由模板 + 同义替换 + 噪声生成，句式多样性低于真实工单；已用 5 种风格缓解，但**不能替代真实数据**。
2. **真值来自构造而非标注**：标签在生成时确定，只能保证「自洽 + 可学习 + 跨模板可迁移」，不能保证「符合真实维修语义」；后者仅由 10 条保真度抽检粗略估计——v1 实测 **5/10 像真实报修、根因 0/10 明显写错**，属「保真度一般、模板化痕迹明显」；替换文案腔后的 **v2 抽检待用户复核**，结果回来前不得写成「修改后保真度提升」。
3. 知识库反推样本仅作补充（<15%），避免「库里有答案」的检索天花板偏差。
4. 关系集相似度用 BGE-M3 CPU 实测；生产检索用的是 embedding-3，落点会有差异，论文报告时须注明模型。
5. 跨模板留出集只有 200 条、3 套模板，仍属「生成分布内」的模板迁移，不是真实分布外泛化。
