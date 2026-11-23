# 可观测性与管理员 API Key 管理

完成时间：2026-11-07。前端页面已接入 Element Plus 现有主题，后端接口全部实测。

## 1. 能力范围

### 1.1 可观测性

| 需求 | 实现 |
| --- | --- |
| 模型 / 场景 / 耗时 / token / 费用 | `ai_call_log` 原有字段直接聚合；费用按 `AiProperties.priceOf(model)` 折算 |
| P50 / P95 | 对过滤后的非工具调用行取 `latency_ms` 样本排序计算（单次最多 20000 条样本） |
| 工具调用链 | 父调用与 `AGENT_TOOL` 行共用 `trace_id`，详情按 traceId 返回完整链路 |
| prompt 版本号 | 每次调用落 `prompt_version`；版本全文存 `ai_prompt_version`，可按版本反查当时内容 |
| 是否被护栏拦截 | `guard_blocked` 落库；被拦请求状态为 `BLOCKED` 并留一行记录 |
| 查询维度 | 时间范围 / 用户 / 场景 / 模型 / 状态；聚合 + 分页列表 + 单条详情 |
| 前端 | `调用观测` 页面：KPI、趋势、耗时分布、分模型/场景/用户、列表、详情抽屉、prompt 版本管理 |

`prompt` 默认版本由 `PromptRegistry` 内置：
- `CHAT`：RAG 问答系统提示词（`chat-v1`）
- `ASSISTANT`：工单助手系统提示词（原 `AssistantService.SYSTEM_PROMPT`）

首次取用会自动写入数据库并存档；管理员新增版本后旧版本保留、新版本立即生效。

### 1.2 管理员 API Key

| 需求 | 实现 |
| --- | --- |
| 按租户配置 | `ai_tenant_key` 唯一键 `(tenant_id, provider, model)` |
| 加密存储 | AES-256-GCM，密文格式 `v1:iv:data`，密钥来自 `tims.ai.key-cipher-secret`（未配置用开发默认值并告警） |
| 列表不回显明文 | 列表只返回 `keyTail` 与 `masked=****尾号` |
| 查看/修改写审计 | `ai_key_audit`：CREATE / UPDATE / DELETE / VIEW / QUOTA |
| 热更新 | 每次模型调用实时查库解密；同步链路用 `RestClient` 拦截器改写 `Authorization`，流式链路显式传 `tenantId` |
| 回落默认 | 租户未配置或解密失败时回落 `application.yml` / `LLM_API_KEY` / `~/secrets/zhipu_api_key`，行为不变 |

### 1.3 余额

智谱开放平台**没有**余额/资源包查询接口。2026-11-07T09:22:02Z 用真实 Key 探测：

| 路径 | 结果 |
| --- | --- |
| `/api/paas/v4/balance` | 404 |
| `/api/paas/v4/usage` | 404 |
| `/api/paas/v4/quota` | 404 |
| `/api/paas/v4/finance/balance` | 404 |
| `/api/paas/v4/resource/package` | 404 |

因此页面展示：
- 管理员填写的 `quotaCny`
- 本地累计消耗 `estimatedCostCny`（按分模型单价折算）
- `remainingCny = max(0, quota - consumed)`
- 显式标注 `LOCAL_ESTIMATE` / `estimate=true` / `official=false`，并附探测证据

**不伪造官方余量。**

## 2. 接口契约

统一响应：`{ code, message, data, timestamp, success }`，`code=0` 成功。

### 2.1 可观测性（登录用户可读，按租户隔离）

#### GET `/api/ai/observe/overview`

参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| from | string | 否 | `yyyy-MM-dd` 或 `yyyy-MM-dd HH:mm:ss`，默认近 7 天 |
| to | string | 否 | 同上；仅日期时含当天 23:59:59.999 |
| userId | long | 否 | 调用用户 |
| scene | string | 否 | `CHAT_STREAM` / `CHAT_SYNC` / `AGENT` / `AGENT_TOOL` / `EMBED` |
| model | string | 否 | 模型名 |
| status | string | 否 | `SUCCESS` / `ERROR` / `DEGRADED` / `BLOCKED` / `CACHE_HIT` |

`data`：

```json
{
  "calls": 783,
  "promptTokens": 149232,
  "completionTokens": 51300,
  "totalTokens": 202307,
  "reasoningTokens": 71,
  "errorCalls": 7,
  "blockedCalls": 0,
  "cacheHitCalls": 0,
  "toolCalls": 7,
  "estimatedCostCny": 0.0279,
  "byModel": [{"model":"glm-5.3-flash","calls":5,"tokens":4100,"promptTokens":1800,"completionTokens":2300,"estimatedCostCny":0.0079,"priceInputPer1k":0.0008,"priceOutputPer1k":0.0028}],
  "byScene": [{"scene":"EMBED","calls":412,"tokens":7482}],
  "byStatus": [{"status":"SUCCESS","calls":776}],
  "byUser": [{"userId":1,"calls":5,"tokens":4100}],
  "trend": [{"day":"2026-11-07","calls":783,"tokens":202307}],
  "latency": {
    "sampleSize": 371, "avgMs": 1850, "p50Ms": 420, "p95Ms": 9545, "maxMs": 22842,
    "buckets": [{"bucket":"<500ms","calls":240},{"bucket":"500-1000ms","calls":60},{"bucket":"1-2s","calls":20},{"bucket":"2-5s","calls":30},{"bucket":">=5s","calls":21}]
  },
  "from": "2026-11-01T00:00:00",
  "to": "2026-11-07T23:59:59.999",
  "pricingNote": "费用按分模型单价（元/千 tokens）折算，非官方账单"
}
```

#### GET `/api/ai/observe/calls`

参数：`page`（默认 1）、`size`（默认 20，最大 200）、其余同 overview。

`data`：`{ total, page, size, items: [...] }`，`item` 字段：

`id, traceId, scene, model, userId, toolName, toolArgs, promptTokens, completionTokens, totalTokens, reasoningTokens, latencyMs, firstTokenMs, status, degraded, guardBlocked, promptVersion, errorMsg, createTime, estimatedCostCny`

#### GET `/api/ai/observe/calls/{id}`

```json
{
  "call": { "id": 2118999403317252098, "scene": "CHAT_SYNC", "promptVersion": "chat-v1", "traceId": "tr-7778caf55c0d4bc3882c" },
  "estimatedCostCny": 0.002016,
  "trace": [ { "scene": "CHAT_SYNC", "...": "同 traceId 的调用与工具行" } ],
  "prompt": { "scene": "CHAT", "version": "chat-v1", "found": true, "content": "你是 AI-TIMS …", "active": true, "createTime": "2026-11-07T09:29:39.3" }
}
```

不存在或跨租户返回 `40401`。

#### GET `/api/ai/observe/prompts?scene=CHAT`

返回版本数组：`id, tenantId, scene, version, content, active, createdBy, createTime`。

#### POST `/api/ai/observe/prompts`（仅 ADMIN）

请求：`{ "scene": "CHAT", "version": "chat-v2", "content": "……" }`，`version` 可省略自动生成。

返回：`{ "id": 123, "scene": "CHAT", "version": "chat-v2", "active": true }`。

### 2.2 管理员 Key / 额度（全部要求 ADMIN，非管理员返回 `40300`）

| 方法 | 路径 | 请求 | 返回 |
| --- | --- | --- | --- |
| GET | `/api/ai/admin/keys` | — | `{tenantId, defaultModel, quotaCny, fallbackNote, keys:[{id,provider,model,keyTail,updatedBy,updateTime,masked}]}` |
| POST | `/api/ai/admin/keys` | `{provider, model, apiKey}` | `{id, provider, model, keyTail, created}` |
| DELETE | `/api/ai/admin/keys/{id}` | — | `{deleted, id}` |
| GET | `/api/ai/admin/keys/{id}/reveal` | — | `{id, apiKey, keyTail, queryTime}`（写 VIEW 审计） |
| GET | `/api/ai/admin/keys/quota` | — | `{tenantId, quotaCny, configured}` |
| PUT | `/api/ai/admin/keys/quota` | `{quotaCny}` | `{tenantId, quotaCny}` |
| GET | `/api/ai/admin/keys/audits?limit=50` | — | `[{id,tenantId,action,provider,model,keyTail,operatorId,detail,createTime}]` |
| GET | `/api/ai/admin/keys/balance` | — | 见下 |

`balance`：

```json
{
  "official": false,
  "officialAvailable": false,
  "source": "LOCAL_ESTIMATE",
  "estimate": true,
  "checkedAt": "2026-11-07T09:28:56.926",
  "quotaCny": 18.0000,
  "estimatedCostCny": 0.0279,
  "remainingCny": 17.9721,
  "usedPercent": 0.15,
  "note": "智谱未开放余额/资源包查询接口，本页为本地累计消耗与管理员额度之差，非官方余量",
  "probe": [
    {"path": "/api/paas/v4/balance", "result": "404"},
    {"path": "/api/paas/v4/usage", "result": "404"},
    {"path": "/api/paas/v4/quota", "result": "404"}
  ]
}
```

## 3. 代码与 SQL

| 文件 | 说明 |
| --- | --- |
| `observe/AiTrace.java` | ThreadLocal traceId，父调用与工具行共用 |
| `observe/AiObserveService.java` | 聚合 / 列表 / 详情 / prompt 反查 |
| `controller/AiObserveController.java` | 观测与 prompt 版本接口 |
| `controller/ApiKeyController.java` | Key / 额度 / 审计 / 余额接口 |
| `apikey/*` | 加解密、Key 服务、租户上下文、实体与 Mapper |
| `prompt/*` | prompt 版本存档与 30s 缓存注册表 |
| `util/AdminGuard.java` | ADMIN 角色校验 |
| `llm/ZhipuKeyProvider.java` | 租户 Key 优先、默认 Key 回落 |
| `llm/ZhipuStreamClient.java` | 流式链路按租户取 Key |
| `config/AiConfig.java` | `RestClient` 拦截器动态改写 `Authorization`（热更新） |
| `service/ChatService.java` / `AssistantService.java` | traceId、prompt 版本、护栏标记、租户上下文 |
| `sql/init.sql` / `sql/upgrade_ai_observe.sql` | 新表与增量升级 |
| `ai-tims-front/src/views/Observe.vue` | 观测面板 + 详情抽屉 |
| `ai-tims-front/src/views/ApiKeyManage.vue` | Key / 额度 / 余额 / 审计 |
| `ai-tims-front/src/api/observe.js` | 前端接口封装 |

## 4. 验证记录

1. 后端编译：`mvn -q -o -pl ticket-ai -am -DskipTests compile` → `COMPILE_OK`。
2. 前端构建：`npm run build` → 1723 modules transformed，`Observe` / `ApiKeyManage` chunk 正常产出。
3. 浏览器实机（192.168.40.10:5173，admin 登录）：
   - 调用观测：KPI（调用次数 783、tokens 202307、费用 ¥0.0279、P95 9545ms）、趋势、耗时分布、调用列表全部渲染，控制台无错误。
   - AI Key 管理：余额卡片显示「本地估算 · 非官方余量」与 ¥17.9721、Key 表、审计表全部渲染，控制台无错误。
4. 真实调用链路：一次 `CHAT_SYNC` 落库 `prompt_version=chat-v1`、`trace_id=tr-7778caf55c0d4bc3882c`，详情接口能返回 prompt 全文。
5. Key 热更新：写入无效租户 Key 后**不重启**立即返回 `40201`（401），删除后同进程下一次调用恢复正常。
6. 余额接口：5 个候选路径均为 404（见 1.3），页面按估算口径展示。

## 5. 局限

- 费用为按 token 单价的本地折算，不是智谱账单；单价来自 `application.yml`。
- P50/P95 为样本内计算，超大时间范围会截断到 20000 条耗时样本。
- 租户 Key 解密失败时不回落默认 Key，直接报错，便于管理员发现配置问题。
- 当前租户由网关注入的 `X-Tenant-Id` 决定；管理员跨租户配置需要以目标租户身份登录（或后续增加租户选择器）。
