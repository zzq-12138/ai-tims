# 公司侧批量补跑 AI 抽取操作手册

> **⚠ 本方案已作废（2026-11-19）。** 需求方改走「按真实业务流程关单、让系统自然发事件」的路线，
> 请改用 [公司批量补跑AI抽取操作手册-v2-真实业务流.md](公司批量补跑AI抽取操作手册-v2-真实业务流.md)。
> 本文件仅作留档：它描述的"直投 q.kb.extract 伪造事件"会把空壳工单送进抽取，结果不可用。

> 适用环境：公司 19.64 集群，namespace `ai-tims`，K8s 1.23.17，kubectl context `kubernetes-admin@kubernetes`。
> 目标：把 `wo_ticket` 里 **104 条从未抽取过** 的有效工单，按生产同款 `ticket.closed` 事件补投一遍，让 `ticket-knowledge` 正常走 AI 抽取。
> 原则：只碰 `ai-tims`；不改工单状态；口令不落任何文件；先 3 条试跑再全量。
> 配套文件：
> - SQL：[20261119_m6_backfill_extract_events.sql](../sql/20261119_m6_backfill_extract_events.sql)
> - 脚本：[m6_backfill_publish.sh](scripts/m6_backfill_publish.sh)
>
> 本手册只描述操作，**没有执行过任何命令**。每一步的「预期输出」都是判定标准，对不上就按「失败判读」停下来查，不要硬着头皮往下跑。

---

## 一、三个关键结论（先看这段，再动手）

### 1.1 默认交换机直投 `q.kb.extract` 可行吗？

**可行，而且这是唯一推荐方式。**

- 队列 `q.kb.extract` 是 durable 队列，名字固定（`RabbitKbConfig.QUEUE`）。RabbitMQ 的默认交换机 `amq.default`（名称为空串）会自动把消息路由到「与 routing key 同名」的队列，所以 `exchange=""` + `routing_key=q.kb.extract` 就能精准投递，不需要预先声明绑定。
- 也可以走 `tims.ticket.event` + `ticket.closed`，但**不要这么做**：该 topic 交换机上同时绑着 `q.push.ticket`（`ticket.#`）。走它会给 ticket-push 再投 104 条「已关单」事件，等于给相关用户推送 104 条伪造的关单通知。直投队列天然绕开这一点。

结论：`exchange = ""`（默认交换机），`routing_key = q.kb.extract`。

### 1.2 在集群里怎么发？不需要装任何东西

镜像 `tims-rabbitmq:3-management` 自带管理插件（15672），但 Pod 里有没有 `rabbitmqadmin` 不确定，**不依赖它**。用现成的两样东西就够：

1. `kubectl port-forward` 把 `tims-rabbitmq-0` 的 15672 映射到 master1 本机；
2. master1 自带的 `curl` 调管理 API：`POST /api/exchanges/%2F/amq.default/publish`。

口令不写在任何文件里：脚本运行时用 `kubectl get secret tims-app-secret -o jsonpath=...` 从集群读出 `RABBIT_PASSWORD`，只在内存里用一次。

### 1.3 会不会改工单状态？—— 分两句说清楚

- **工单状态机 `wo_ticket.status` 不会变**，`version`、处理人、流转日志 `wo_ticket_flow` 都不会变。这条成立，依据是 `ExtractionService` 全程只读工单详情，唯一回写是 `OrderClient.markAiExtracted()`，而它只把 `wo_ticket.ai_extracted` 置 1。
- **但 `wo_ticket.ai_extracted` 这个标记会从 0 变成 1**（仅当该条抽取成功）。它不是状态机状态，只影响「AI 采纳率」统计（`StatService` 用 `ai_extracted=1 且 CLOSED` 算采纳率）。如果你要求连这个标记也不动，只能放弃补跑；或者跑完后按第 9 章把它复位。

---

## 二、代码依据（有争议时以代码为准）

| 项 | 事实 | 出处 |
|---|---|---|
| 消费者 | `TicketClosedConsumer` 监听 `q.kb.extract`，只处理 `eventType = ticket.closed`；`tenantId` 缺省 1 | `ticket-knowledge/.../consumer/TicketClosedConsumer.java` |
| 事件字段 | 只读 `eventType`、`tenantId`、`ticketId`、`ticketNo`、`deviceType`；`ticketId` 必须能转成数字 | 同上 + `ExtractionService.handleClosedEvent` |
| 幂等 | 先 `selectCount(tenant_id, source_ticket_id)`，有记录直接跳过；再靠唯一键 `uk_tenant_ticket` 兜并发 | `ExtractionService` / `docs/sql/20261118_schema_full.sql` |
| 落库节奏 | 先插一条 `status=PROCESSING`，再异步抽取，结束改 `PENDING_REVIEW` 或 `MANUAL_REQUIRED` | `ExtractionService.processRow` |
| 执行器 | core 16 / max 32 / 有界队列 200，默认拒绝策略 `CallerRunsPolicy`（不抛异常、由调用线程兜底执行） | `ExtractExecutorConfig` + `application.yml` |
| 死信 | 队列参数 `x-dead-letter-exchange=""`、routing key `q.kb.extract.dead`；监听容器 `default-requeue-rejected=false`、重试 3 次 | `RabbitKbConfig` + `application.yml` |
| 知识库写入 | 抽取只写 `ai_extracted`，**不写** `kb_knowledge`、**不写** Milvus；只有审核「通过/合并」才写 | `ExtractionReviewService.approve/merge` |
| 工单回写 | 抽取成功后调 `POST /api/order/ticket/{id}/ai-extracted`，只置 `ai_extracted=1` | `OrderClient.markAiExtracted` + `TicketService.markAiExtracted` |
| 超时 | 内部 RestTemplate 连接 5s、读 150s，覆盖单条 9~10s 的抽取 | `InternalRestConfig` |

> 已确认一个细节：`markAiExtracted` 用的 `updateById` 只带 `id + ai_extracted`，不会因为 `version` 为 null 而覆盖乐观锁版本，也不会动 `status`。

---

## 三、准备（master1，运维账号，只读）

### 3.1 上传两个文件到 master1

本机（Windows 仓库）→ master1：`/data/sdv1/tims/backfill/`

用 WinSCP 或 scp 都可以。到 master1 后先建目录并核对 MD5（数值见本次交付回复，或与仓库文件 `certutil -hashfile <文件> MD5` 对比）：

```bash
mkdir -p /data/sdv1/tims/backfill
ls -l /data/sdv1/tims/backfill
md5sum /data/sdv1/tims/backfill/m6_backfill_publish.sh
md5sum /data/sdv1/tims/backfill/20261119_m6_backfill_extract_events.sql
```

**预期**：两个文件存在，MD5 与仓库侧一致。
**失败判读**：MD5 不一致说明传输截断，重新传，不要用改过的脚本跑。

### 3.2 集群预检

```bash
kubectl config current-context
kubectl -n ai-tims get pod -l app=tims-rabbitmq -o wide
kubectl -n ai-tims get pod -l app=ticket-knowledge
kubectl -n ai-tims exec deploy/ticket-knowledge -- env | grep -E '^RABBIT_(HOST|USER)=' || true
kubectl -n ai-tims exec deploy/ticket-knowledge -- env | grep -E '^KB_EXTRACT_POOL|^LLM_EXTRACT_MODEL=' || true
```

**预期**：
- context 是 `kubernetes-admin@kubernetes`；
- `tims-rabbitmq-0` 为 `1/1 Running`；
- `ticket-knowledge` 的 Pod 为 `1/1 Running`；
- 看到 `RABBIT_HOST=tims-rabbitmq`、`RABBIT_USER=tims`；
- `KB_EXTRACT_POOL_*` **可能一行都没有** —— 这不是故障，说明用的是代码默认值（core 16 / max 32 / queue 200 / CallerRunsPolicy）。

**失败判读**：
- 找不到 rabbitmq Pod：先 `kubectl -n ai-tims get sts`，确认 StatefulSet 存在且副本为 1；Pod 没起来先别继续。
- `ticket-knowledge` 不是 Running：队列没人声明、也没人消费，投进去只会堆积，必须先修服务。
- 如果 `KB_EXTRACT_POOL_REJECTION` 显示为 `AbortPolicy`，请在第 10 章风险 1 里记一笔（默认不是它）。

---

## 四、第一步：SQL 盘点（公司虚拟桌面，Navicat）

连接：`172.27.19.64:30546`，库 `aitims`，用户 `root`（沿用历史操作口径）。
打开 [20261119_m6_backfill_extract_events.sql](../sql/20261119_m6_backfill_extract_events.sql)，按顺序跑 0.1 ~ 0.5，**这一段全是 SELECT，不会改数据**。

| 查询 | 预期结果 | 对不上怎么办 |
|---|---|---|
| 0.1 状态分布 | 合计 **105** 条，CLOSED 占绝大多数 | 先停下，确认 `deleted=0` 的口径是否与"有效工单 105"一致 |
| 0.2 已有抽取 | **1 条**，`MANUAL_REQUIRED`，工单号 `WO20261118-0105` | 多于 1 条说明期间有人跑过，把实际条数记下来 |
| 0.3 待补跑 | **104** | 不是 104 就把实际数字抄下来，后文所有 3 / 101 的分段按实际数字调整 |
| 0.4 待补跑状态分布 | 理想情况全为 `CLOSED` | 若混入 DRAFT/PROCESSING：建议在 1.2 段打开 `AND t.status = 'CLOSED'`，只跑已关闭工单（数量会小于 104，分段数字同步改） |
| 0.5 基线 | 一行 `bak_max_id` + 时间 | **把这两个值抄到操作记录里**，回滚只认它 |

> `bak_max_id` 的作用：`ai_extracted.id` 是雪花主键，单调递增。跑批前记下最大值，跑批后 `id > bak_max_id` 就是"本次新增"，回滚范围精确且不用维护 104 个工单号。

---

## 五、第二步：生成 payload 文件（104 行，一行一个 JSON）

跑 SQL 文件 **1.2 段**，得到一列 `payload`。三种落地方式，任选其一。

### 方式 A：虚拟桌面有 mysql 客户端（最省事）

**在 cmd.exe 里执行**（不要在 Windows PowerShell 5.1 里用 `>` 重定向：PS5 默认写 UTF-16，脚本读不了；要用 PowerShell 就改用 `| Out-File -Encoding utf8 payloads.jsonl`）：

```bat
mysql -h172.27.19.64 -P30546 -uroot -p --default-character-set=utf8mb4 --batch --raw --skip-column-names aitims -e "SELECT JSON_OBJECT('eventType','ticket.closed','tenantId',t.tenant_id,'ticketId',t.id,'ticketNo',t.ticket_no,'deviceType',t.device_type) FROM wo_ticket t LEFT JOIN ai_extracted a ON a.tenant_id=t.tenant_id AND a.source_ticket_id=t.id AND a.deleted=0 WHERE t.deleted=0 AND a.id IS NULL ORDER BY t.id;" > payloads.jsonl
```

> 若只跑已关闭工单，在上面 `WHERE` 后补 `AND t.status='CLOSED'`。`-p` 后不要跟密码，交互输入。
> 生成后用 WinSCP 把 `payloads.jsonl` 传到 master1 的 `/data/sdv1/tims/backfill/`。


### 方式 B：用 Navicat 导出

1. 跑 SQL 文件 1.2 段；
2. 结果网格 → 右键 →「导出结果」→ 格式选「文本文件」；
3. **取消勾选**「包含列标题 / 字段名」；
4. 编码选 UTF-8，保存为 `payloads.txt`；
5. 用 WinSCP 上传到 master1 的 `/data/sdv1/tims/backfill/payloads.jsonl`。

> 脚本已经兼容 Navicat 的 CSV 包裹格式：整行被双引号包住会去掉外层引号，`""` 会还原成 `"`，BOM 和 CRLF 也会清掉。**不要**手动编辑每一行。

### 方式 C：没有 mysql 客户端、也不想导出

桌面跑 1.2 段，把结果网格那一列复制出来，走剪贴板到 master1，用 heredoc 落盘：

```bash
cat > /data/sdv1/tims/backfill/payloads.jsonl <<'JSONL_EOF'
<这里粘贴 104 行，一行一条，不要加逗号>
JSONL_EOF
```

> heredoc 用单引号定界符，粘贴内容里的 `$`、反引号不会被展开。

### 落盘后校验（master1）

```bash
cd /data/sdv1/tims/backfill
awk 'NF' payloads.jsonl | wc -l
awk 'NF' payloads.jsonl | grep -c '"eventType"'
awk 'NF' payloads.jsonl | grep -vc '^{'
head -n 2 payloads.jsonl
```

**预期**：`104` / `104` / `0`，前两行形如
`{"eventType": "ticket.closed", "tenantId": 1, "ticketId": 1234567890123456789, "ticketNo": "WO20261118-0001", "deviceType": "..."}`
（MySQL 8 的 `JSON_OBJECT` 在冒号后带空格，属正常，不影响消费）。

**失败判读**：
- 行数不是 104 → 导出时丢了行，或 SQL 里还带着未预期的过滤条件；
- 第三行计数 > 0 → 有行不是以 `{` 开头（典型原因：复制时混入表头、行号或逗号）。**如果只有 1 行且是文件第一行，多半是 UTF-8 BOM**，去掉即可：
  `sed -i '1s/^\xEF\xBB\xBF//' /data/sdv1/tims/backfill/payloads.jsonl`（脚本本身也会剥 BOM，这里只是让校验数干净）；
- 出现 `ticketId` 不是数字 → 选错了列（应该是 JSON 那一列，不是工单号列）。

用 `--dry-run` 先看一眼脚本会发什么（不连 RabbitMQ）：

```bash
bash /data/sdv1/tims/backfill/m6_backfill_publish.sh \
  --file /data/sdv1/tims/backfill/payloads.jsonl --limit 3 --dry-run
```

---

## 六、第三步：3 条试跑 + 核对（master1）

### 6.1 发出前记两个数

- 桌面 SQL 0.5 的 `bak_max_id`；
- master1 当前时间 `date '+%F %T'`（与库的 `NOW()` 时区一致，都是 Asia/Shanghai）。

### 6.2 投递 3 条

```bash
bash /data/sdv1/tims/backfill/m6_backfill_publish.sh \
  --file /data/sdv1/tims/backfill/payloads.jsonl --limit 3
```

**预期输出（关键行）**：

```
  本次发送    : 3 条
  队列状态(前): {"name":"q.kb.extract","state":"running","messages_ready":0,...}
== 开始投递：3 条 -> q.kb.extract ==
...
== 投递结束 ==
  成功 routed: 3
  失败       : 0
  队列状态(后): {"name":"q.kb.extract",...,"messages_ready":0,...}
  死信队列(后): {"name":"q.kb.extract.dead",...,"messages_ready":0,...}
```

`routed: true` 表示消息确实进了队列。`messages_ready` 可能瞬间是 3、也可能已经是 0（消费很快），都正常。

**失败判读**：

| 现象 | 原因 | 处置 |
|---|---|---|
| `在 namespace ai-tims 找不到 app=tims-rabbitmq 的 Pod` | label 不对或 Pod 未起 | `kubectl -n ai-tims get pod --show-labels` 核对 |
| `管理 API 未就绪` | 15672 未映射成功 / 口令不对（401）/ 端口被占 | 看脚本打印的 port-forward 日志；换 `LOCAL_PORT=15673` 重试 |
| `队列 q.kb.extract 不存在` | ticket-knowledge 未启动（队列由它声明） | 先把服务拉起，再重跑本步 |
| `routed: false` | 队列名或 vhost 不对 | 核对 `QUEUE`、`/api/queues/%2F/q.kb.extract` |
| 第 N 条 `不是以 { 开头的 JSON` | payload 文件混入脏行 | 修文件，重跑（已发的 3 条不会重复落库，幂等） |

### 6.3 核对这 3 条是否真的抽了（公司虚拟桌面）

先取这 3 条的 ticketId：

```bash
head -n 3 /data/sdv1/tims/backfill/payloads.jsonl | grep -oE '"ticketId"[[:space:]]*:[[:space:]]*[0-9]+'
```

再在 Navicat 里查（把三个 id 填进去）：

```sql
SELECT id, source_ticket_id, source_ticket_no, status, dedup_action,
       LEFT(error_msg, 80) AS error_msg, create_time
FROM ai_extracted
WHERE tenant_id = 1
  AND source_ticket_id IN (<id1>, <id2>, <id3>)
ORDER BY create_time;
```

**预期**：3 行，`status = PENDING_REVIEW`，`title` 等字段非空；通常 30 秒内完成（单条 9~10 秒，3 条并发）。

**失败判读**：

| 现象 | 含义 | 处置 |
|---|---|---|
| 3 行都是 `PROCESSING` 且超过 3 分钟 | 异步任务卡住 / Pod 重启丢任务 | 看 `kubectl -n ai-tims logs deploy/ticket-knowledge --tail=200`，搜 `[m6] 工单` |
| 出现 `MANUAL_REQUIRED` | 抽取失败，原因在 `error_msg` | 若写「工单详情获取失败」→ 查 ticket-order；写「AI 抽取失败」→ 查 ticket-ai/vLLM；修好后可重跑（需先删该行，见 7.3） |
| 一行都没有 | 消息被投到死信（反序列化失败） | 查 `q.kb.extract.dead` 数量与 knowledge 日志里的 `MessageConversionException` |
| 只有 2 行 | 有一条重复消息被幂等跳过（说明之前抽过） | 看 0.3 是否本来就不含它，属正常 |

### 6.4 看队列执行器指标（master1，可选但建议）

```bash
kubectl -n ai-tims port-forward deploy/ticket-knowledge 18103:8103 >/tmp/pf-kb.log 2>&1 &
sleep 2
curl -s http://127.0.0.1:18103/internal/kb/extract/queue-stats; echo
kill %1
```

**预期**：`submitted >= 3`、`completed >= 3`、`failed = 0`、`rejected = 0`、`queueDepth = 0`、`active = 0`。
这些计数是「Pod 启动以来累计值」，请用增量判断，不要拿绝对值当本次结果。

---

## 七、第四步：全量投剩余 101 条（master1）

### 7.1 投递

```bash
bash /data/sdv1/tims/backfill/m6_backfill_publish.sh \
  --file /data/sdv1/tims/backfill/payloads.jsonl --offset 3
```

- `--offset 3` = 跳过前 3 条（试跑已发过），只发剩下的 101 条。
- 若你的实际总数不是 104（比如只跑 CLOSED 是 98），把 `--offset 3` 保持不变即可，脚本会自动发剩余的。

**预期**：`成功 routed: 101`、`失败: 0`。
**失败判读**：与 6.2 的表一致；任何一条失败脚本会立刻停下，已发的消息不会重复消费（幂等），修好后从失败位置继续（用 `--offset` 手动跳过已成功的条数）。

### 7.2 跑批期间观察（每 30 秒采样一次，共约 2.5 分钟，可重复多轮）

```bash
kubectl -n ai-tims port-forward deploy/ticket-knowledge 18103:8103 >/tmp/pf-kb.log 2>&1 &
PF=$!
sleep 2
for i in 1 2 3 4 5; do
  curl -s http://127.0.0.1:18103/internal/kb/extract/queue-stats; echo
  sleep 30
done
kill $PF
```

**预期**：`queueDepth` 从 100 左右逐步降到 0，`active` 在 10~16 之间，`completed` 持续上涨，`failed` 不涨。

### 7.3 单条失败后如何重跑（重要）

`alreadyExtracted` 只要表里有行（`deleted=0`）就跳过，所以**不能直接重投**。要重跑某一条：

```sql
-- 只删这一条（把 <TICKET_ID> 换成该工单 id）
DELETE FROM ai_extracted
WHERE tenant_id = 1 AND source_ticket_id = <TICKET_ID> AND status IN ('MANUAL_REQUIRED','PROCESSING');
```

然后把这条单独写成一个文件重投：

```bash
grep '"ticketId"[[:space:]]*:[[:space:]]*<TICKET_ID>[,}]' /data/sdv1/tims/backfill/payloads.jsonl > /tmp/one.jsonl
bash /data/sdv1/tims/backfill/m6_backfill_publish.sh --file /tmp/one.jsonl
```

> **不要用软删**（`UPDATE ... SET deleted=1`）：唯一键 `uk_tenant_ticket` 不看 `deleted`，软删后重投会撞唯一键，被消费者当成"重复消息"静默忽略，且不会报错——排查起来非常浪费时间。

---

## 八、第五步：全量结果核对（公司虚拟桌面）

```sql
-- 8.1 总条数：预期 105（104 新增 + 原有 1 条）
SELECT COUNT(*) AS total FROM ai_extracted WHERE tenant_id = 1 AND deleted = 0;

-- 8.2 状态分布：PENDING_REVIEW ≈ 成功条数；MANUAL_REQUIRED = 失败条数
SELECT status, COUNT(*) AS cnt, MIN(create_time) AS first_at, MAX(create_time) AS last_at
FROM ai_extracted WHERE tenant_id = 1 AND deleted = 0
GROUP BY status ORDER BY cnt DESC;

-- 8.3 残留 PROCESSING：预期 0 行
SELECT id, source_ticket_no, status,
       TIMESTAMPDIFF(MINUTE, create_time, NOW()) AS minutes_in_processing
FROM ai_extracted WHERE tenant_id = 1 AND status = 'PROCESSING';

-- 8.4 本次新增明细（把 <BAK_MAX_ID> 换成 0.5 记的值），重点看 error_msg
SELECT id, source_ticket_no, status, dedup_action, dedup_note,
       LEFT(error_msg, 100) AS error_msg, create_time
FROM ai_extracted WHERE tenant_id = 1 AND id > <BAK_MAX_ID>
ORDER BY id;

-- 8.5 工单侧核对：status 全部保持原值，只有 ai_extracted 变 1
SELECT t.status, t.ai_extracted, COUNT(*) AS cnt
FROM wo_ticket t
WHERE t.id IN (SELECT source_ticket_id FROM ai_extracted WHERE tenant_id = 1 AND id > <BAK_MAX_ID>)
GROUP BY t.status, t.ai_extracted;
```

**判定为完成的条件**（同时满足）：

1. 8.1 = 105，8.3 = 0；
2. 8.2 中 `MANUAL_REQUIRED` 的条数可以逐个解释（每条都看过 `error_msg`）；
3. 8.5 里 `status` 分布与跑批前一致答案（跑前没记录就对比 0.1，工单总数与状态不能被本次操作改变）。

另外确认死信队列没涨：

```bash
# master1，脚本会打印前后两次死信队列状态；也可手工查
kubectl -n ai-tims port-forward pod/tims-rabbitmq-0 15672:15672 >/tmp/pf-mq.log 2>&1 &
sleep 2
curl -s -u "tims:<口令>" \
  "http://127.0.0.1:15672/api/queues/%2F/q.kb.extract.dead?columns=name,messages_ready"
kill %1
```

> 手工查要把 `<口令>` 换成真实值——这一步是唯一需要手输口令的地方，命令不要写进任何脚本或文档。也可以用脚本同样的办法从 Secret 取：
> `PASS=$(kubectl -n ai-tims get secret tims-app-secret -o jsonpath='{.data.RABBIT_PASSWORD}' | base64 -d)`

**预期**：`messages_ready = 0`（跑批前是多少，跑完还是多少）。

---

## 九、回滚

### 9.1 影响面先讲清楚

| 对象 | 本次操作会不会改 | 回滚要不要处理 |
|---|---|---|
| `ai_extracted` | 会：新增 104 行（`PENDING_REVIEW` 或 `MANUAL_REQUIRED`） | 要，删除本次新增行 |
| `wo_ticket.status` / `version` / 处理人 / 流转日志 | **不会** | 不用处理 |
| `wo_ticket.ai_extracted` | 会：抽取成功的工单由 0 → 1 | 可选，按 9.2 第 ③ 步复位 |
| `kb_knowledge` | **不会**（只有审核"通过/合并"才写） | 不用处理 |
| Milvus 向量 | **不会**（向量同步只消费 `kb_knowledge` 中已发布条目） | 不用处理 |
| ticket-ai 用量表 | 会：每条抽取成功后做相似度，会回传 1 条 EMBED 用量（仅计费统计） | 不用回滚，属于正常用量 |

所以「不改工单状态」这条成立；唯一需要解释的副作用是 `ai_extracted` 标记位。

### 9.2 回滚顺序（执行前必须确认没有 PROCESSING 残留）

```sql
-- ① 先确认没有异步任务还在跑：预期 0 行
SELECT COUNT(*) FROM ai_extracted WHERE tenant_id = 1 AND status = 'PROCESSING';

-- ② 预览要删的行
SELECT id, source_ticket_no, status, create_time
FROM ai_extracted WHERE tenant_id = 1 AND id > <BAK_MAX_ID> ORDER BY id;

-- ③ 复位工单标记（可选；先做，因为它依赖 ai_extracted 还没删）
UPDATE wo_ticket t
  JOIN ai_extracted a ON a.tenant_id = t.tenant_id AND a.source_ticket_id = t.id
SET t.ai_extracted = 0
WHERE a.tenant_id = 1 AND a.id > <BAK_MAX_ID>;

-- ④ 硬删本次新增的抽取行
DELETE FROM ai_extracted WHERE tenant_id = 1 AND id > <BAK_MAX_ID>;

-- ⑤ 复核：应只剩 1 条 MANUAL_REQUIRED
SELECT status, COUNT(*) FROM ai_extracted WHERE tenant_id = 1 AND deleted = 0 GROUP BY status;
```

注意事项：
- **必须硬删**，理由见 7.3（软删占唯一键）；
- 如果 ① 不为 0，先等异步任务跑完再删，否则删完后任务回写 `updateById` 影响 0 行，但 `markAiExtracted` 仍会把工单标记置 1，出现"表里没行、工单标记是 1"的不一致；
- Navicat 若开了「安全更新模式」，`UPDATE ... JOIN` 可能被拦，按提示关闭 safe updates 或改用显式 id 列表。

---

## 十、已知风险与耗时预估

1. **队列满 → RejectedExecutionException 转人工**：现行配置 `rejection-policy=CallerRunsPolicy`，**不会抛这个异常**：队列（200 槽）+ 最大线程（32）合计可容纳 232 个任务，远大于 104，本批从容量上就不可能触发。真正会转人工的是"抽取失败"（AI 超时、详情接口失败），落 `MANUAL_REQUIRED`。检查是否被改过：`kubectl -n ai-tims exec deploy/ticket-knowledge -- env | grep KB_EXTRACT_POOL_REJECTION`，显示 `abort` 才需要担心。
2. **单条 9~10 秒**：104 条串行约 16~17 分钟；按 16 线程并发理论约 1 分钟。实际瓶颈是内网 vLLM 的并发能力，**建议预留 5~20 分钟观察窗口**，以 `queue-stats` 的 `completed` 增长为准，不要按固定时间认定失败。
3. **ticket-ai / vLLM 不可用**：整批 `MANUAL_REQUIRED`，此时不必慌乱，修好服务后按 7.3 逐条重跑（或整批回滚后重来）。
4. **消息格式不对导致反序列化失败**：监听容器 `default-requeue-rejected=false` + 重试 3 次，最终进 `q.kb.extract.dead`。这正是"先跑 3 条"的意义——格式问题会在试跑阶段暴露，不会一次性污染 104 条。
5. **审核中心突然多 104 条待审**：`PENDING_REVIEW` 会全部出现在审核列表，注意答辩前的评审排期，不要误点「通过」。
6. **LLM 调用费用**：本批会产生约 104 次抽取调用（失败重试会更多），按公司内网 vLLM 计费口径自行核算。
7. **不要与真实关单高峰重叠**：虽然幂等键保证同一工单不会重复，但队列与模型并发会被抢占，建议挑空闲时段。

---

## 十一、那条已存在的 `MANUAL_REQUIRED`（WO20261118-0105）怎么处理

它已经有一行记录，`alreadyExtracted` 会直接跳过，所以**再投事件不会重新抽取**。两个方案：

**方案 A（推荐，零风险）**：不重抽。在审核中心打开这条，按工单原始内容人工补录标题/现象/步骤，保存后状态会由 `MANUAL_REQUIRED` 自动转 `PENDING_REVIEW`（`ExtractionReviewService.update` 里写死的），再决定通过或驳回。

**方案 B（想重新让 AI 抽一次）**：

```sql
-- ① 找到工单 id
SELECT id, ticket_no, status FROM wo_ticket WHERE ticket_no = 'WO20261118-0105' AND deleted = 0;

-- ② 只删这一条（确认 id 无误后执行）
DELETE FROM ai_extracted WHERE tenant_id = 1 AND source_ticket_id = <ID> AND status = 'MANUAL_REQUIRED';
```

然后单发一条事件：

```bash
grep -E '"ticketNo"[[:space:]]*:[[:space:]]*"WO20261118-0105"' /data/sdv1/tims/backfill/payloads.jsonl > /tmp/wo105.jsonl
# 如果全量 payload 里没有它（因为它被 0.3 的排除条件过滤掉了），手工写一行：
cat > /tmp/wo105.jsonl <<'EOF'
{"eventType":"ticket.closed","tenantId":1,"ticketId":<ID>,"ticketNo":"WO20261118-0105","deviceType":"<原设备类型>"}
EOF
bash /data/sdv1/tims/backfill/m6_backfill_publish.sh --file /tmp/wo105.jsonl
```

> 注意：全量 payload 是按"排除已有抽取记录"生成的，**不会包含这条**，所以多数情况要走手工写一行的分支。写之前先从 0.2 的结果里抄 `deviceType`（可为 null，那就不写这个字段）。

---

## 十二、故障判读速查

| 现象 | 最可能原因 | 处置 |
|---|---|---|
| `routed: true` 但库里一直没新行 | 消费者没连上队列 / 事件被幂等跳过 | `kubectl logs deploy/ticket-knowledge --tail=200 \| grep '\[m6\]'`；确认该 ticketId 本来不在表里 |
| 日志出现 `MessageConversionException` | 消息体 / content_type 不对 | 死信数量会涨；检查 payload 是否为单行 JSON、`content_type=application/json` |
| 大量 `MANUAL_REQUIRED`，`error_msg` 含「工单详情获取失败」 | ticket-order 不可用，或工单被删 | `kubectl -n ai-tims logs deploy/ticket-order --tail=100`，或直接 curl 内部详情接口 |
| 大量 `MANUAL_REQUIRED`，`error_msg` 含「AI 抽取失败」 | ticket-ai / vLLM 超时或 5xx | `kubectl -n ai-tims logs deploy/ticket-ai --tail=100`；确认 vLLM 地址可用 |
| `PROCESSING` 长时间不动 | Pod 重启导致内存任务丢失 | 等 5 分钟；仍不动按 7.3 删行重投 |
| 队列 `messages_ready` 一直不降 | 消费者掉线 / prefetch 占满 | 看 knowledge 日志与 `/internal/kb/extract/queue-stats` 的 `active` |
| 管理 API 401 | Secret 口令与 RabbitMQ 实际口令不一致 | 用部署时注入的口令核对；不要改 Secret |
| `routed: false` | 队列名打错 or vhost 不是 `/` | 核对 `/api/queues/%2F/q.kb.extract` |

---

## 十三、执行后回填（按项目文档制度）

跑完后请在 [公司环境操作记录.md](公司环境操作记录.md) 追加一条记录，至少包含：执行时间、机器、`bak_max_id`、发送条数、成功/失败条数、状态分布、异常的 `error_msg` 摘要、是否回滚。这样下次答辩或复盘能直接对上账。
