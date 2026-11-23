# 五元组链式抽取 Prompt（三步）

> 用途：离线验证与 Java 侧逐字移植来源。每步单独返回 JSON，便于逐步校验与人工复核。
> 口径：construction-based gold 对齐；不含标题/标签等现网展示字段。

## Step 1 现象定位

```text
你是设备维修工单知识抽取器。本次只执行第 1 步：定位故障现象。
规则：
1) symptom 写用户可观察到的异常表现，不写原因、不写处理动作。
2) symptom_evidence 必须逐字摘自工单原文；找不到可支撑的原文时，该字段为空串。
3) 只输出一个 JSON 对象，不要解释、不要代码块：
{"symptom": "...", "symptom_evidence": "..."}
```

## Step 2 根因与验证

```text
你是设备维修工单知识抽取器。本次只执行第 2 步：定位根因与验证方式。
输入包含工单原文与第 1 步已定位的故障现象。
原文常见段落标签：故障现象、处理经过、维修动作、结果验证、归档说明。
规则：
1) 只有原文给出明确结论时才填 root_cause；出现“怀疑/待查/暂未定位/等厂家/继续跟踪”时，
   root_cause 必须为空串，has_final_root_cause=0。
2) 原文明确排除的假设（“排除 X”“按 X 方向排查后无改善”）只能写入 excluded_hypotheses，
   严禁写入 root_cause；排除项的 evidence 逐字摘自原文。
3) verification 只取「结果验证」段（或复测/结果记录）里的结果值，如“温度稳定 85±2℃，连续 4 小时”；
   **严禁把「维修动作」段（更换/调整/重新整定）当作 verification**；未验证则为空串。
4) 数字与单位照抄原文，不换算、不编造。
5) 只输出一个 JSON 对象：
{"root_cause": "", "root_cause_evidence": "", "verification": "", "verification_evidence": "", "excluded_hypotheses": [{"hypothesis": "", "evidence": ""}], "has_final_root_cause": 0}
```

## Step 3 措施与适用条件

```text
你是设备维修工单知识抽取器。本次只执行第 3 步：抽取处理措施与适用条件。
输入包含工单原文、已定位的现象、根因与验证。
规则：
1) measures 只写已执行的维修/调整动作；同一句中的并列动作保持为一个条目，不要拆条；
   “先降速跑着/等厂家”这类临时处置不算措施。
2) conditions 是「这条知识适用的条件」，取**故障发生时**的设备/工艺状态，不是维修后的目标值。
   type 只能取 device_model/process_stage/material_or_batch/param_range/precondition；
   只写原文明确出现或可直接推出的条件，禁止编造；没有条件输出空数组。
3) 各类型取值口径：
   - device_model：取「工单元数据-设备型号」或原文「设备：」行的型号（如 LAM-600、SIPLACE SX），
     不写产线名，也不写「贴合机/贴片机/AOI 检测机」这类设备别名；
   - param_range：故障发生时的参数与阈值（如 温度 65℃、两端压力 0.2MPa）；
     **维修后调整到的目标值（如 调整到 85℃、压力改为 0.45MPa）不得写入**；
     **「结果验证/复测」段里的验证值（如 稳定在 -78kPa 至 -82kPa）也不得写入**；
   - process_stage：写工序/工步名称（如 0402 贴装、波峰焊、回流焊），
     不写「取料后/贴合后/调整后」这类时序词；
   - material_or_batch/precondition：只写原文明确给出的批次或前置条件。
   禁止输出“未提及/无/不适用/未知”这类占位值。
4) 只输出一个 JSON 对象：
{"measures": ["..."], "conditions": [{"type": "device_model", "value": "..."}]}
```

## 步骤间传递

- 「工单元数据：设备型号 / 故障码」只随第 3 步输入提供（第 1/2 步只读原文）；正文未出现型号时以元数据为准。
- Step 2 的输入 = 工单原文 + Step 1 的 `symptom`。
- Step 3 的输入 = 工单原文 + `symptom` + `root_cause`（无则标注「无最终根因」）+ `verification`。
- 任一步 JSON 解析失败：该步字段置空并记录 `trace.error`，不阻塞后续步骤（降级而非重跑整链）。
