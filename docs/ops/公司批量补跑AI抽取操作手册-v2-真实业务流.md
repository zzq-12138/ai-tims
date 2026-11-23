# 公司侧补跑 AI 抽取（真实业务流版）操作手册

> 适用环境：公司 19.64 集群，namespace `ai-tims`，K8s 1.23.17；库 `aitims`（`172.27.19.64:30546`）。
> 目标：把 104 条空壳工单按**真实业务接口**走完「受理 → 开工 → 解决 → 关闭」，由 `confirm` 在事务提交后自然发出 `ticket.closed`，让 ticket-knowledge 按生产链路抽取。
> 前提：**只碰 `ai-tims` 与 `aitims`；不改代码；不执行任何命令（本手册由你亲手跑）**。
> 与旧版关系：旧版《公司批量补跑AI抽取操作手册》里的「直接投 ticket.closed」方案**作废**，不要再用。
>
> 配套文件：
> - 脚本：[m6_flow_backfill.py](scripts/m6_flow_backfill.py)
> - 核对 SQL：[20261119_m6_flow_backfill_verify.sql](../sql/20261119_m6_flow_backfill_verify.sql)

---

## 一、先看结论：为什么是四步，不是三步

### 1.1 状态机不允许跳过「开工」

代码里的迁移表是唯一事实来源（[TicketStateMachine.java](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-order/src/main/java/com/tims/order/statemachine/TicketStateMachine.java#L34-L52)）：

```
SUBMITTED --accept--> ACCEPTED --start--> PROCESSING --resolve--> RESOLVED --confirm--> CLOSED
```

- `resolve` 的前置状态**只能是 `PROCESSING`**，直接从 `SUBMITTED` 调 resolve 会返回 `20401 非法状态迁移`；
- 所以每张单的真实动作序列是 **accept → start → resolve → confirm** 四步（你说的"受理 → 解决 → 关闭"少了 start）；
- 那 1 条已经是 `PROCESSING` 的工单，从 **resolve** 开始，两步完成。

### 1.2 权限：ADMIN 可以全程代处理

逐接口看守卫（[TicketService.java](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-order/src/main/java/com/tims/order/service/TicketService.java#L314-L420)）：

| 动作 | 允许的角色/人 | 本方案怎么满足 |
|---|---|---|
| accept | ADMIN / DISPATCHER / ENGINEER / 当前处理人 | 用 ADMIN 账号，直接过 |
| start | **当前处理人或 ADMIN** | 同上；不需要先改处理人 |
| resolve | **当前处理人或 ADMIN** | 同上，「只有当前处理人能解决」这条 guard 由 ADMIN 白名单绕开 |
| confirm | **创建人或 ADMIN** | 同上 |
| resume | 当前处理人或 ADMIN | 仅当遇到 SUSPENDED 时用到 |

也就是说：**一个 ADMIN 账号就能把 104 条全部代处理完**，不用 assign、不用改 `handler_id`。副作用是 `wo_ticket_flow.operator_name` 全记成这个管理员——这在"代班组补录"的口径下是合理且可解释的。

如果坚持让处理人自己解决：先 `POST /api/order/ticket/{id}/assign` 把处理人改成你的账号（ADMIN 允许转派），再执行后三步。多两条流转记录，意义不大，本手册不采用。

### 1.3 `ticket.closed` 只在 confirm 时发，且是事务提交后发

[applyTransition](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-order/src/main/java/com/tims/order/service/TicketService.java#L422-L457) 里只有 `CONFIRM` 分支会 `publish("ticket.closed")`；[EventPublisher](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-order/src/main/java/com/tims/order/service/EventPublisher.java#L66-L104) 注册的是 `afterCommit`，事务回滚就不会发。事件走 topic 交换机 `tims.ticket.event`，同时被两个队列消费：

- `q.kb.extract` → ticket-knowledge 抽取（我们要的）；
- `q.push.ticket` → ticket-push 给**在线坐席**推一条 WS 轻通知（[PushPipeline](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-push/src/main/java/com/tims/push/service/PushPipeline.java#L153-L162)：不落站内信、不写库）。

### 1.4 本次会改什么、不会改什么

| 对象 | 变化 |
|---|---|
| `wo_ticket.status` | SUBMITTED→ACCEPTED→PROCESSING→RESOLVED→CLOSED（**不可逆**） |
| `wo_ticket.resolve_note` | 写入模板生成的处置结论（2000 字以内） |
| `wo_ticket.current_node` | 01 填报 → 02 处理 → 03 确认 |
| `wo_ticket.ai_extracted` | 抽取成功后 0 → 1 |
| `wo_ticket_flow` | 每张 SUBMITTED 单 +4 条，PROCESSING 单 +2 条（**只追加**） |
| `ai_extracted` | 每张单 +1 行（PENDING_REVIEW 或 MANUAL_REQUIRED） |
| `kb_knowledge` / Milvus | **不变**（只有审核"通过"才写） |

---

## 二、动手前先确认事实（只读）

| 项 | 事实 | 依据 |
|---|---|---|
| 网关地址 | `http://10.96.0.18:8080`（ClusterIP，master1 上直连可用，10.15 条记录用过）；备用 NodePort `172.27.19.64:30204` | `docs/ops/公司环境操作记录.md` 10.15 / 10.30 |
| 登录接口 | `POST /api/auth/login`，body `{"username","password"}`，返回 `data.token` | `AuthController` |
| 鉴权头 | `Authorization: <token>`（token-name 就是 `Authorization`，无 Bearer 前缀） | ticket-order / gateway `application.yml` |
| 工单列表 | `GET /api/order/ticket/page?tab=ALL&page=1&size=200` | `TicketPageQuery` |
| 状态接口 | `POST /ticket/{id}/accept|start|resolve|confirm` | `TicketController` |
| resolve 入参 | `{"resolveNote":"..."}`，非空、≤2000 字 | `ResolveDTO` |
| 抽取输入 | `工单编号/标题/设备类型/故障描述/解决说明/流转记录` | `ChainExtractionService.buildSourceText` |
| 抽取失败 | 即时重试 1 次，仍失败 → `MANUAL_REQUIRED` | `ExtractionService.processRow` |

---

## 三、准备（master1，有 root 权限的运维账号）

### 3.1 放文件、查 Python

脚本依赖 **Python 3 标准库**（无需 pip）。先确认：

```bash
python3 -V
```

**预期**：`Python 3.x.x`。
**失败判读**：没有 python3 → 改在**开发笔记本**上跑（仓库 `scripts/` 都是 Python，环境肯定有），用 `--base-url http://172.27.19.64:30204` 直连 NodePort。不要装东西。

把脚本上传到 master1：

```bash
mkdir -p /data/sdv1/tims/backfill
ls -l /data/sdv1/tims/backfill/m6_flow_backfill.py
md5sum /data/sdv1/tims/backfill/m6_flow_backfill.py
```

**预期**：文件存在，MD5 与交付回复里给的一致。
**失败判读**：MD5 不一致 = 传输截断，重传。

### 3.2 测网关连通

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://10.96.0.18:8080/api/order/ping
```

**预期**：`200`（或 `404` 但能返回——说明网关通、路由通）。
**失败判读**：`000`/超时 → 网关不在或地址变了；改用 `http://172.27.19.64:30204/api/order/ping` 再试一次。

### 3.3 选一种方式拿身份

**方式 A（推荐）：脚本交互登录，密码不进任何地方**

```bash
cd /data/sdv1/tims/backfill
python3 m6_flow_backfill.py --username admin --limit 2 --dry-run
```

执行后提示 `xxx 的密码:`，输入即可（getpass 不回显、不进 shell 历史）。

> 公司库的种子管理员账号是 `admin`（角色 `ADMIN`），密码按现场约定，脚本交互输入。
> 脚本拿到身份后会先调 `/api/auth/me` 校验角色：不是 ADMIN 直接退出，避免跑到第 2 步才 403。

> 注意：连续输错会触发账号锁定 + 来源 IP 封禁（`AuthService.login` 的双维度计数），一次输对。

**方式 B：用浏览器里的 token**

前端登录后，F12 → Network → 找 `/api/auth/login` 响应里的 `data.token`；然后：

```bash
read -s -p "token: " TIMS_TOKEN; echo
export TIMS_TOKEN
```

**失败判读**：返回 `10401 未登录或凭证失效` → token 过期/复制少了字符，重新登录取一次。

### 3.4 只读看一眼健康度（可选）

```bash
kubectl -n ai-tims get pod -l app=ticket-order
kubectl -n ai-tims get pod -l app=ticket-knowledge
kubectl -n ai-tims logs deploy/ticket-knowledge --tail=30 | grep -E '\[m6\]|ERROR' || true
```

**预期**：两个 Pod `1/1 Running`；日志无持续报错。
**失败判读**：knowledge 不在跑 → 关闭工单后没人抽取，先修服务再开跑。

---

## 四、备份（必须先做，先于任何写操作）

状态机不可逆、`wo_ticket_flow` 只追加、接口没有"撤销关单"，**回滚只有一条路：跑前整表备份 + 整表恢复**。不要相信"删几行就能回去"。

### 4.1 备份范围

| 表 | 为什么备 |
|---|---|
| `wo_ticket` | 状态、resolve_note、ai_extracted 标记全在这 |
| `wo_ticket_flow` | 只追加，恢复必须连它一起回退 |
| `ai_extracted` | 本批新增的抽取行也一并回退 |

### 4.2 执行备份（公司虚拟桌面，**cmd.exe**）

```bat
mkdir D:\tims_backup
mysqldump -h172.27.19.64 -P30546 -uroot -p --single-transaction --no-tablespaces --default-character-set=utf8mb4 --set-gtid-purged=OFF --add-drop-table aitims wo_ticket wo_ticket_flow ai_extracted > D:\tims_backup\aitims_m6flow_20261119_2100.sql
```

- `-p` 后不跟密码，交互输入；**口令不要写进任何文件**；
- 若报 `Unknown option '--no-tablespaces'` 或 `'--set-gtid-purged'`，去掉对应参数重跑（低版本客户端不支持）；
- 建议挑一个没有别人在操作工单的时间点。

### 4.3 校验备份（三件事都要做）

```bat
dir D:\tims_backup\aitims_m6flow_20261119_2100.sql
findstr /C:"CREATE TABLE" D:\tims_backup\aitims_m6flow_20261119_2100.sql | find /C "CREATE TABLE"
findstr /C:"Dump completed" D:\tims_backup\aitims_m6flow_20261119_2100.sql
certutil -hashfile D:\tims_backup\aitims_m6flow_20261119_2100.sql MD5
```

**预期**：
- 文件大小 > 1 MB（105 张工单 + 流转日志）；
- `CREATE TABLE` 恰好 **3** 次；
- 输出含 `-- Dump completed on ...`；
- 得到一个 MD5，抄进操作记录。

**失败判读**：
- 只有 0 字节 → 口令错或权限不足，看 stderr；
- `CREATE TABLE` 少于 3 → 表名拼错；
- 没有 `Dump completed` → 导出中断，必须重导（中途断掉的 dump 不能用来恢复）。

再把行数基线记下来（Navicat，SQL 文件 §0.3）：

```sql
SELECT 'wo_ticket' AS tbl, COUNT(*) AS cnt FROM wo_ticket
UNION ALL SELECT 'wo_ticket_flow', COUNT(*) FROM wo_ticket_flow
UNION ALL SELECT 'ai_extracted', COUNT(*) FROM ai_extracted;
```

**预期**：`wo_ticket` 105、`ai_extracted` 1；`wo_ticket_flow` 以查询结果为准（至少 105，每张单都有 CREATE 记录）。这三个数字与备份文件、恢复后的结果必须一一对上。

最后把 dump 复制一份到 master1 留档（可选但建议）：

```bash
ls -l /data/sdv1/tims/backups/
```

### 4.4 恢复（只在需要回滚时执行）

```bat
mysql -h172.27.19.64 -P30546 -uroot -p --default-character-set=utf8mb4 aitims < D:\tims_backup\aitims_m6flow_20261119_2100.sql
```

**必须知道的三件事**：

1. dump 里带 `DROP TABLE` + `CREATE TABLE`，恢复 = **用备份时点覆盖这三张表**；
2. 备份之后产生的**所有**工单变更都会消失——包括别人新建的工单、别人处理的单。执行前必须确认没人在用；
3. Redis 里的工单流水号不会回退，恢复后新建工单号可能跳号，**无害**。

恢复后复核：跑 SQL 文件 §0.1~0.3，三个数字要和备份前完全一致；再抽查一张工单的 `status`、`resolve_note`。

---

## 五、`resolve_note` 模板（脚本为准，这里同步展示）

### 5.1 三条硬约束（来自抽取提示词，不是我们的偏好）

链式抽取对原文有明确规则（[ChainExtractionService](file:///g:/JAVA/Code/ai-tims/ai-tims-parent/ticket-ai/src/main/java/com/tims/ai/service/ChainExtractionService.java#L56-L104)）：

1. `symptom_evidence`、`root_cause_evidence` 必须**逐字摘自原文** → 结论要写成完整句子，别只写关键词；
2. 原文出现「怀疑 / 待查 / 暂未定位 / 等厂家 / 继续跟踪」时，`root_cause` 会被**强制清空**、`has_final_root_cause=0` → 模板里一个这类词都不能有（脚本会自检拦截）；
3. `verification` 只取"结果验证"段的**结果值**，不能把维修动作当验证 → 必须有一句带数值的复测结论。

### 5.2 生成的固定结构

```
故障现象：<按本设备的指标/工艺限/故障前值渲染的具体越限句>。
处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，重点检查<单元>；<本设备的点检动作>；结合历史同类工单排除来料与人为操作因素。
根因：<本设备专属的机构/参数结论，不用"液路"之类的通用套话>。
维修动作：<本设备专属的处置动作>。
结果验证：<带数值的复测结果，数值必须与现象句的"故障前/修复后"一致>。
归档说明：<点检/监控要求>。
```

现象行**不再复述标题**。mock 生成的标题就是「设备类型 + 工单类型 + -模拟#12345」，复述等于什么都没写；现在改为用 `DEVICES[device]` 里的 `metric / limit_text / before` 渲染一句具体越限描述，再让后面的根因、维修、验证引用同一组数值。

### 5.3 设备专属故障机理（脚本 `DEVICES`）

| 设备 | 现象句（用哪组数） | 设备专属根因（设备异常） | 维修动作 |
|---|---|---|---|
| 贴片机 | 抛料率由工艺上限 0.5% 升至 1.8%，触发报警并停线 | 供料器齿轮磨损 + 吸嘴密封圈老化，吸嘴真空度 85→52 kPa（标准 ≥80 kPa） | 换密封圈与供料器齿轮、清真空管路、重校准识别相机与贴装坐标 |
| AOI检测机 | 误报率由 2.0% 升至 6.2%，良品被判不良、复检积压 | 光源模组衰减 + 镜头防护玻璃污染，成像对比度不足 | 换光源模组、清洁镜头与防护玻璃、相机标定与灰度校正 |
| 涂布机 | 涂层厚度由 42±2 μm 漂移至 46.5 μm，批量超差 | 刮刀刃口磨损 + 供料泵出口压力波动 | 换刮刀并调间隙、清洗泵与过滤网、排气后恢复供料 |
| 贴合机 | 贴合气泡率由 1.0% 升至 3.5%，抽检连续不良 | 压合密封条老化，压合压力 0.25→0.18 MPa | 换密封条、清洁压合面、重整定压力与温度曲线 |
| 蚀刻机 | 蚀刻均匀性由 95% 降至 88%，线宽超差返工 | 喷淋喷嘴部分堵塞 + 药液过滤芯饱和，喷淋压力不足 | 疏通喷嘴、换过滤芯、按工艺补加药液 |
| 其他设备 | 无编造数值，走通用六段句 | 执行机构磨损或传感单元参数漂移 | 换磨损件、清传动与气路、校准传感器零点 |

> 机理按设备实际机构写：贴片机只写供料器 / 吸嘴 / 真空，**没有液路**就不写液路；AOI 写光学与成像；涂布、蚀刻才涉及液路与药液。

### 5.4 工单类型句模板（脚本 `TYPE_*`）

| 工单类型 | 现象行 | 根因 | 处置动作 | 结果验证 |
|---|---|---|---|---|
| 设备异常 | 指标由工艺上限/窗口/下限恶化到故障前值，触发报警 | 设备专属机构结论（见 5.3） | 设备专属 fix + 复位空跑 30 分钟 | 指标由 {故障前} 降至/回升至 {修复后}（{工艺限}），连续 4 小时无报警 |
| 品质异常 | 同上，强调批量外观/尺寸不良 | 设备专属参数漂移结论，来料与人为因素已排除 | 设备专属 tune + 连续 3 批首件与抽检 | 连续 3 批合格，指标稳定在 {修复后}（{工艺限}） |
| 系统异常 | 上位机连续报超限、采集曲线有断点、**现场实测指标正常** | 设备本体正常，通讯链路间歇中断导致丢点误判 | 换通讯线缆、重启采集模块、补采断点数据 | 连续 2 小时无丢包，数据完整率 100%，重复报警消失 |
| 其他 | 同设备异常 | 设备专属机构结论 | 设备专属 fix | 指标由 {故障前} 恢复至 {修复后}，连续 4 小时无异常 |

> 设备不在 `DEVICES` 里时走 `build_generic_note()`：同样是六段自洽结论（现象→处理→根因→维修→验证→归档），但不编造具体数值，也不会退回复述标题。

### 5.5 三条渲染实例（与脚本输出逐字一致）

**① 贴片机 / 设备异常**

```
故障现象：贴片机抛料率近 3 个批次由工艺上限 0.5% 持续升至 1.8%，连续触发超限报警并造成当班停线。
处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，重点检查贴片头与供料器；逐站核对吸嘴真空度（标准 ≥80 kPa）与供料器步进定位，清洁吸嘴与反光板；结合历史同类工单排除来料与人为操作因素。
根因：经分段排查定位为供料器齿轮磨损叠加吸嘴密封圈老化，吸嘴真空度由 85 kPa 降至 52 kPa，元件吸取失败导致抛料率持续超标。
维修动作：更换磨损的吸嘴密封圈与供料器齿轮，清洁真空管路，重新校准元件识别相机与贴装坐标；复位后空跑 30 分钟确认动作稳定。
结果验证：抛料率由 1.8% 降至 0.3%（工艺上限 0.5%），连续运行 4 小时未再触发报警。
归档说明：将该点位纳入班前点检，指标触及工艺边界时立即停机检查。
```

**② AOI检测机 / 品质异常**

```
故障现象：AOI 检测机误报率近 3 个批次由工艺上限 2.0% 升至 6.2%，复判确认大量良品被判为不良，当班复检积压。
处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，重点检查光学成像与光源模块；核对光源亮度衰减曲线与相机对焦状态，复判近 200 片已检板确认误报分布；结合历史同类工单排除来料与人为操作因素。
根因：复测确认误报率随批次漂移并超出控制限 2.0%，定位为检测程序阈值与元件库参数未随新批次更新，来料与人为操作因素已排除。
维修动作：复核检测程序阈值与元件库，按首件结果重新标定判定参数；连续生产 3 批做首件与抽检确认。
结果验证：连续 3 批首件与抽检均合格，误报率稳定在 1.1%（工艺上限 2.0%）。
归档说明：在 SPC 中对误报率加严监控，连续 3 批触及控制限即触发工程复核。
```

**③ 涂布机 / 系统异常**

```
故障现象：涂布机上位机近 3 个批次连续报出超限报警，同时段采集曲线存在断点，现场实测工艺指标正常。
处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，重点检查刮刀与供料泵；测量刮刀间隙与供料泵出口压力，抽测三处涂层厚度确认偏差方向；结合历史同类工单排除来料与人为操作因素。
根因：排查确认涂布机本体运行正常，异常来自设备与上位机的通讯链路间歇中断，采集数据丢点导致系统误判超限。
维修动作：更换涂布机至上位机的通讯线缆，重启采集模块；补采断点期间数据并核对采集服务日志。
结果验证：通讯恢复后连续 2 小时无丢包，采集数据完整率 100%，重复报警消失。
归档说明：把该通讯链路纳入网络巡检清单，交换机端口做绑定与告警。
```

> 这些数值是按设备类型编的**演示口径**，不是真实维修记录。答辩时要主动说明，别把它讲成真实生产数据（见第十章风险 4）。

---

## 六、试点 2 条（master1）

### 6.1 先 dry-run，只看不写

```bash
cd /data/sdv1/tims/backfill
python3 m6_flow_backfill.py --username admin --limit 2 --dry-run
```

**预期输出**：

```
  登录成功：admin
  工单总数 105，本次候选 104 条（dry-run）
  节奏：每条间隔 20.0s，每 10 条停 60.0s

[1/2] WO20261119-0001 id=2123... 贴片机 设备异常 现状=SUBMITTED 计划=accept → start → resolve → confirm → CLOSED
    resolve_note：
      故障现象：贴片机抛料率近 3 个批次由工艺上限 0.5% 持续升至 1.8%，连续触发超限报警并造成当班停线。
      处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，重点检查贴片头与供料器；...
```

**失败判读**：
- `网关不可达` → 回 3.2 换地址；
- `登录失败` → 账号密码/角色问题（必须是 ADMIN）；
- 输出 `模板校验失败` → 模板里混进了禁用词，属于脚本被改坏，恢复原版。

**这一步要把两条 note 从头读到尾**：像不像人写的、跟设备类型/工单类型对不对得上、六段数值是否前后一致。不满意就改脚本模板后再 dry-run，不要往下走。

### 6.2 正式跑试点

```bash
python3 m6_flow_backfill.py --username admin --limit 2
```

**预期**：每条打印

```
[1/2] WO20261119-0001 id=... 现状=SUBMITTED 开始推进
    OK accept → start → resolve → confirm 终态=CLOSED
...
== 本次结果：成功 2 条，失败 0 条 ==
   日志：/data/sdv1/tims/backfill/m6_flow_run_20261119_XXXXXX.log
```

**失败判读**：

| 报错 | 原因 | 处置 |
|---|---|---|
| `code=20401 非法状态迁移` | 该单状态被别人改过 | 重新 dry-run 看当前状态，按提示处理 |
| `code=20402 工单状态已被其他操作变更` | 并发冲突（乐观锁） | 直接重跑同一命令，脚本按当前状态续做 |
| `code=10403 仅管理员/调度员...` | 账号不是 ADMIN | 换账号 |
| `code=10403 仅当前处理人或管理员...` | 同上 | 同上 |
| `HTTP 401 code=10401` | token 过期 | 重新登录 |
| `连接失败` | 网络抖动 | 重跑，已完成的单会被跳过 |

### 6.3 立即核对（公司虚拟桌面，Navicat）

取试点两单的 id（脚本日志里有），跑 SQL 文件 **§1.2 / §1.3 / §1.4**。

**§1.2 预期**：两行 `status=CLOSED`、`current_node=03 确认`、`note_len ≥ 250`。
（`ai_extracted` 标记要等异步抽取完成才置 1，刚关单时可能还是 0，以 §1.4 为准。）

**§1.3 预期**：每张单 5 条流转记录，顺序为
`CREATE(SUBMITTED) → ACCEPT(SUBMITTED→ACCEPTED) → START(ACCEPTED→PROCESSING) → RESOLVE(PROCESSING→RESOLVED) → CONFIRM(RESOLVED→CLOSED)`，
`operator_name` 是你们用的 ADMIN 账号。

**§1.4 预期**（关单后等 20~30 秒再查）：每张单 1 行 `ai_extracted`，`status=PENDING_REVIEW`。

### 6.4 质检判定（逐项打勾，缺一不可）

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | 工单状态 | `CLOSED` |
| 2 | resolve_note | 非空，长度 ≥ 250，含"根因""维修动作""结果验证" |
| 3 | 流转日志 | 4 条新增，from/to 与 1.3 完全一致 |
| 4 | 抽取行 | `status=PENDING_REVIEW`，无 `error_msg` |
| 5 | title | 非空，且不等于工单号 |
| 6 | fault_phenomenon | 非空，且写出了**指标名 + 具体数值/方向**（如"抛料率升至 1.8%"），不是复述标题 |
| 7 | root_cause | **非空**，且 `has_final_root_cause = 1` |
| 8 | solution_steps | 非空，能看出至少 2 个处置动作 |
| 9 | verification | 非空且带数值/结果值 |

**任一项不通过 → 停下，不要全量。** 处理分支：

- 若是 5/6/7 的质量问题：先看 `chain_trace` 定位是哪一步降级：
  ```sql
  SELECT source_ticket_no, LEFT(chain_trace, 400) FROM ai_extracted
  WHERE tenant_id=1 AND source_ticket_id IN (<ID1>, <ID2>);
  ```
  常见原因：模板里出现禁用措辞（7 空）、结论写得太笼统（7 空）、验证段写成动作（9 空）。改脚本模板 → 重新 dry-run 看文本 → **用第四章备份恢复** → 重跑试点。
- 若只是措辞不理想但字段齐全：可以继续，但要在操作记录里写明"试点质量已人工确认"。

---

## 七、全量跑剩余 102 条

### 7.1 节奏怎么定（并发控制）

每条 `confirm` 会触发一次异步抽取，单条 9~10 秒。脚本默认：

- `--interval 20`：每条关闭后等 20 秒再处理下一条 ⇒ 任意时刻在跑的抽取约 1~2 条；
- `--pause-every 10 --pause-seconds 60`：每 10 条再停 1 分钟，让队列彻底消化。

按此节奏：104 条 ≈ 104×21.6 秒 + 10×60 秒 ≈ **47 分钟**（不含核对）。想更快可以降到 `--interval 12`（并发约 3~4 条），**不建议低于 10 秒**。

脚本不会并发调用，也不会批量 pre-fetch，所以不会像直投事件那样瞬间塞满队列。

### 7.2 执行

```bash
cd /data/sdv1/tims/backfill
python3 m6_flow_backfill.py --username admin
```

默认会跳过已 CLOSED 的（包括试点 2 条和原本那 1 条），只处理剩下的 102 条。

**中途想停**：`Ctrl+C`。当前这条可能停在 ACCEPTED/PROCESSING/RESOLVED 任一状态，重跑会从该状态续做（见第九章）。

### 7.3 期间观察（另开一个终端，master1）

```bash
kubectl -n ai-tims port-forward deploy/ticket-knowledge 18103:8103 >/tmp/pf-kb.log 2>&1 &
sleep 2
curl -s http://127.0.0.1:18103/internal/kb/extract/queue-stats; echo
```

**预期**：`queueDepth` 长期在 0~3，`active` 在 0~3，`failed` 不涨。

```bash
kubectl -n ai-tims logs deploy/ticket-order --tail=50 | grep '事件发布-MQ' | tail -5
kubectl -n ai-tims logs deploy/ticket-knowledge --tail=50 | grep '\[m6\]' | tail -10
```

**预期**：order 持续打印 `[事件发布-MQ] ticket.closed ticketId=...`；knowledge 打印 `已入抽取队列` / `抽取完成 status=PENDING_REVIEW`。

**失败判读**：
- `queueDepth` 只涨不降 → knowledge 消费卡住或 vLLM 慢，先 `Ctrl+C` 停脚本，查日志再继续；
- 连续出现 `status=MANUAL_REQUIRED` → 看 `error_msg`（AI 失败/详情失败），修好后继续；
- `事件发布` 走的是 `HTTP降级`/`Redis兜底` → MQ 有问题，先停下排查，别继续制造事件。

---

## 八、跑完核对（公司虚拟桌面）

按 SQL 文件 §2 全部跑一遍，重点看：

| 查询 | 预期 | 不达标怎么办 |
|---|---|---|
| 2.1 状态分布 | `CLOSED=105`，`SUBMITTED/PROCESSING=0` | 有残留 → 说明脚本没跑完，重跑续做 |
| 2.2 抽取总数 | `105` | 少了 → 看 2.5 是否有关单未抽取 |
| 2.3 状态分布 | `PENDING_REVIEW` 为主，`MANUAL_REQUIRED` 逐条可解释 | 逐条看 `error_msg` |
| 2.4 PROCESSING 残留 | `0` | 等 5 分钟再看；仍不动按 9.3 处理 |
| 2.5 关单但无抽取行 | `0` | 事件丢失/消费失败，查 knowledge 日志 |
| 2.6 有抽取但未关单 | `0` | 数据不一致，人工排查 |
| 2.8 流转总数 | 备份前 + **414**（103×4 + 1×2） | 差值不对 → 说明有单走了别的路径，逐条核 |

最后人工抽 5 条（§3）读一遍 `fault_phenomenon / root_cause / solution_steps`，确认不是空话。

---

## 九、中断与续跑

### 9.1 为什么可以直接重跑

脚本每做一步之前都先 `GET /ticket/{id}` 读真实状态，再决定下一个动作；已经 CLOSED 的单直接跳过。所以：

- 网络断了、`Ctrl+C`、Pod 重启，**再执行同一条命令即可**；
- 不会重复 ACCEPT/START（状态已变，脚本不会再调）；
- `resolve` 只会执行一次（执行后状态变 RESOLVED，下一步就是 confirm）。

### 9.2 只想补特定的单

```bash
python3 m6_flow_backfill.py --username admin --ids 2123...,2123...
```

### 9.3 单条卡在 PROCESSING 或抽取失败

- 工单卡在 PROCESSING：直接重跑，脚本会继续 resolve → confirm；
- 工单已 CLOSED 但 `ai_extracted` 是 `MANUAL_REQUIRED`：本方案**不重发事件**（真实业务里关单只发一次）。处理方式只有人工补录（审核中心编辑后提交），或者接受这条不参与知识库。这属于业务真实结果，不是脚本缺陷。

---

## 十、风险与答辩口径

1. **不可逆**：关单没有反向接口，`wo_ticket_flow` 只追加。**没有备份就不要开跑**；恢复会覆盖备份时点之后的所有工单变更。
2. **推送打扰**：每张关单会给**当时的在线坐席**推一条 WS 通知（不落库、不写站内信）。若有人开着页面，会连收 100+ 条。建议提前告知，或挑下班后跑。
3. **vLLM 压力**：默认节奏下并发 1~2 条，对模型基本无感；不要改成并发脚本。104 次抽取会产生相应 token 消耗，按内网口径自行记账。
4. **数据性质要说清**：这 103 条来自 `POST /api/order/mock/batch`，标题是「{设备}{类型}-模拟#xxxxx」，描述是「模拟工单：…指标越限触发自动上报」。`resolve_note` 是按设备类型套模板补录的处置结论。**答辩时必须说明这是演示数据、用于验证链路与抽取字段完整性，不代表真实维修记录**，否则一旦被追问维修细节会站不住。
5. **"模拟"字样会进入抽取结果**：描述里的"模拟工单"可能被模型写进 `fault_phenomenon`。若在意，可在备份后、开跑前把描述前缀去掉：
   ```sql
   -- 可选，不属于"真实业务流"，默认不执行
   UPDATE wo_ticket SET description = REPLACE(description, '模拟工单：', '')
   WHERE deleted = 0 AND description LIKE '模拟工单：%';
   ```
   代价是偏离"原样数据"，需在操作记录里写明。
6. **口令/令牌**：只用交互输入或环境变量；不要把 token 写进脚本、文档、日志。跑完在前端退出登录可让 token 失效。
7. **并发冲突**：若有人同时在页面上操作同一张单，会返回 `20402`，脚本停止；重跑即可。
8. **审核压力**：跑完审核中心会多出 104 条 `PENDING_REVIEW`，不要在答辩前误点「通过」——一通过就会写 `kb_knowledge` 并同步 Milvus。

---

## 十一、跑完追加到 `docs/ops/公司环境操作记录.md`

在该文件"十、"章节末尾追加一条（编号顺延，如 10.31），格式照现有条目：

```markdown
### 10.31 真实业务流批量补跑 AI 抽取（2026-11-19）

| 项 | 内容 |
|---|---|
| 时间 | 2026-11-19 HH:MM ~ HH:MM |
| 机器 | master1（脚本执行）+ 公司虚拟桌面 Navicat（SQL 核对） |
| 备份 | `D:\tims_backup\aitims_m6flow_20261119_HHMM.sql`，MD5 `____`，`wo_ticket` ___ 行 / `wo_ticket_flow` ___ 行 / `ai_extracted` ___ 行 |
| 命令 | `python3 m6_flow_backfill.py --username admin --limit 2`（试点）；`python3 m6_flow_backfill.py --username admin`（全量）；日志 `m6_flow_run_20261119_HHMMSS.log` |
| 输出 | 试点 2 条、全量 102 条全部 `CLOSED`；`wo_ticket_flow` 新增 414 条；`ai_extracted` 新增 ___ 条 |
| 判读 | 状态分布 CLOSED __ / 其他 __；`ai_extracted` PENDING_REVIEW __ / MANUAL_REQUIRED __；`PROCESSING` 残留 0；关单无抽取 0 |
| 回滚 | 未执行。如需回滚：`mysql -h172.27.19.64 -P30546 -uroot -p aitims < <备份文件>`（会覆盖备份时点后的全部工单变更） |
```

---

## 十二、执行清单（照着勾）

- [ ] 备份三张表 + 校验 MD5/CREATE TABLE/Dump completed + 记录行数基线
- [ ] `python3 -V` 通过，脚本 MD5 对上
- [ ] 网关切通（`/api/order/ping`）
- [ ] dry-run 两条，人工读 note
- [ ] 试点 2 条，SQL §1.2/1.3/1.4 全绿
- [ ] 试点质检 9 项全过（尤其 `has_final_root_cause=1`）
- [ ] 全量 102 条，期间盯 `queue-stats` 与日志
- [ ] 跑完 SQL §2 全绿，抽检 5 条
- [ ] 追加操作记录，写清备份路径与 MD5
