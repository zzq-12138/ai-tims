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
