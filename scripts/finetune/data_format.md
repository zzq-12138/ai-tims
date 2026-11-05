# 工单 → 五元组训练样本格式（v1）

面向问题二（知识抽取 / 三关系判别 / 条件化）的 LoRA 训练数据约定。标注手册、训练脚本、评测脚本共用本格式。

## 1. 一行一条（JSONL）

```json
{"id":"WO-000001","device_type":"贴片机","input":{"symptom_text":"贴装头在运行过程中突然撞击工作台面，设备报警 E207 停机","device_model":"SMT-2070","process":"SMT 贴装"},"output":{"phenomenon":"贴装头运行中撞击工作台面并报 E207","root_cause":"伺服耦合器松动导致位置反馈偏差","measures":["紧固耦合器","重新标定原点","空跑 30 分钟验证"],"verification":"连续 3 批无再报警","applicable_conditions":{"device":"贴片机","model":"SMT-2070","process":"SMT 贴装","preconditions":"设备已完成日常点检"},"excluded_hypotheses":[{"hypothesis":"来料批次异常","reason":"同批次其他机台无同类故障"}]}}
```

## 2. 字段定义

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `id` | string | 是 | 工单号，全库唯一；用于切分与溯源 |
| `device_type` | string | 是 | 设备族（贴片机/回流焊/AOI/键合机/清洗机/划片机/MES） |
| `input.symptom_text` | string | 是 | 现场原始描述，保留口语与噪声；不得改写成"标准故障名" |
| `input.device_model` | string | 否 | 型号；缺失写 `"未知"`（训练时保留缺失，模拟真实缺字段） |
| `input.process` | string | 否 | 工序；缺失写 `"未知"` |
| `output.phenomenon` | string | 是 | **现象**：可观测事实，不含推断 |
| `output.root_cause` | string | 是 | **根因**：可验证的失效机理/部件 |
| `output.measures` | string[] | 是 | **措施**：按执行顺序排列，1~6 条 |
| `output.verification` | string | 是 | **验证结果**：量化或可观测的确认（如"抛料率 2.1%→0.32%"） |
| `output.applicable_conditions` | object | 是 | **条件化**：`device/model/process/preconditions` 四键齐全，缺失填 `"不限"` |
| `output.excluded_hypotheses` | array | 是 | **假设负例**：被排除的错误根因 + 排除理由；无则 `[]`（不可缺字段） |

## 3. 三关系（判别任务的对齐口径）

| 关系 | 定义 | 训练信号 |
|---|---|---|
| R1 现象 → 根因 | 同一现象可对应多个根因；样本必须给出唯一确定根因 + 被排除项 | `root_cause` + `excluded_hypotheses` |
| R2 根因 → 措施 | 措施须与根因因果一致，不能是"通用保养话术" | `measures` 与 `root_cause` 一致 |
| R3 措施 → 验证 | 每条样本必须有可观测验证，不能只写"恢复正常" | `verification` 含量化阈值/时长 |
| 条件化 | 同一根因在不同设备/型号/工序下适用性不同 | `applicable_conditions` |

## 4. 训练时的文本构造

- prompt：`system`（固定抽取指令）+ `user`（`工单文本 / 设备类型 / 设备型号`）。
- target：`output` 的**紧凑 JSON**（`ensure_ascii=False, separators=(",", ":")`）+ `eos`。
- loss 只计算 target 段（prompt 段 label = `-100`）。
- `文档去重`：`id` 唯一；同一工单的多次改写只能保留一条进入 train，其余进 test 时需按 `id` 分组切分，避免泄漏。

## 5. 质检规则（入库前脚本校验）

1. `id` 唯一、非空；`device_type` 在允许集合内。
2. `output` 六个键齐全；`measures` 长度 1~6；`verification` 非空且不是"已解决/正常"这类空话。
3. `applicable_conditions` 四键齐全，值非空。
4. `excluded_hypotheses` 至少 0 条、最多 3 条；每条含 `hypothesis` 与 `reason`。
5. target JSON 可被 `json.loads` 解析；token 长度 ≤ `seq_len`（超长截断需人工复核，不允许静默截断）。
6. `symptom_text` 不得与 `phenomenon` 完全同义复制（否则模型学"复述"而非"抽取"）。

## 6. 与评测的对应

- 抽取评测：字段级 F1（六键分别算），`measures` 用集合匹配。
- 关系评测：R1/R2/R3 逐条二分类准确率 + 混淆矩阵。
- 条件化评测：`applicable_conditions` 四键准确率；缺字段输入下的鲁棒性单列切片。
