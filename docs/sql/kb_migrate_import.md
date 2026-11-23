# 知识库数据迁移：开发机 → 公司内网（操作说明）

> 配套文件：
> - `docs/sql/kb_migrate_export.sh`：在开发机导出（`kb_category` + `kb_knowledge` 的数据）
> - `docs/sql/kb_migrate_verify.sql`：导入后的只读校验
>
> **和 `docs/sql/20261118_schema_full.sql` 的区别**：后者是「空库一键建表」脚本，明确不导出任何业务数据；
> 本次是「已有表结构、只搬数据」，不建表、不改结构。两者不要混用：
> 新环境先跑 schema_full 建表，再用本次的 dump 灌数据；已经建好表的环境**不要**再跑 schema_full。

---

## 0. 迁移范围与已知情况

| 项 | 值 |
|---|---|
| 源库 | 开发机 `aitims`.`kb_knowledge`，共 320 条（318 PUBLISHED + 2 PENDING） |
| 同时导出 | `kb_category`（知识分类，条数很少） |
| 不导出 | Milvus 向量（开发机用智谱 embedding-3，公司用 Qwen3-Embedding-8B，模型不同，向量不可复用） |
| 公司库现状 | `kb_knowledge` 只有 1 条测试知识，`id=2122940268192731138`，已 PUBLISHED、已向量化 |
| 迁移后 | 321 条；需把迁移进来的行 `vector_synced_at` 置空，由公司模型重算向量 |

两个「看起来像问题、其实不是问题」的点：

1. **53 条知识带 `source_ticket_id`**：对应的工单在公司库不存在。这是**业务语义上的外键**，`kb_knowledge` 表上**没有数据库外键约束**（见建表脚本第 184 行，只有普通字段），所以导入不会失败；只是从这些知识点回跳工单会打不开。
2. **257 条 `create_by` 为 NULL**：导入后「创建人」列是空的。列表接口不做创建人过滤，**不影响展示和检索**。是否统一回填为 1（admin）由业务定，回填语句见 4.4。

---

## 1. 传输路线（和镜像包同一条链路）

```
开发机 dev@192.168.40.10
     │  scp（在台式机上执行，笔记本到不了开发机）
     ▼
台式机 → 笔记本 D:\kb_migrate\        （走远程桌面的驱动器重定向）
     │
     ▼
公司虚拟桌面（挂载笔记本的 D 盘）
     │  复制到 master1
     ▼
master1:/data/sdv1/tims/sql/kb_migrate_YYYYmmdd.sql
```

要点：

- 大文件走「台式机 → 笔记本 → 虚拟桌面」的物理中转，不要在笔记本上直接 scp 开发机。
- 笔记本上放 `D:\kb_migrate\`，**不要放 C 盘**（C 盘空间紧张）。
- 传完核对 md5：导出脚本会生成 `kb_migrate_YYYYmmdd.sql.md5`，两边 `md5sum` 必须一致再导入。

在 master1 上建目录（如还没有）：

```bash
mkdir -p /data/sdv1/tims/sql && ls -l /data/sdv1/tims/sql
```

> 说明：这个 SQL 最终是给虚拟桌面里的 Navicat 用，放到 master1 只是为了归档留底；如果传输链路不方便，也可以直接从虚拟桌面读到文件后拖进 Navicat 打开。

---

## 2. 导入前检查（3 分钟，必须做）

### 2.1 记录基线（回滚要靠它）

在 Navicat 里连公司库，先执行：

```sql
USE aitims;

-- 现有知识条数与那 1 条测试知识
SELECT COUNT(*) AS before_total FROM kb_knowledge;
SELECT id, title, status, vector_synced_at FROM kb_knowledge;

-- 现有分类（决定 kb_category 那段能不能直接执行）
SELECT id, category_name FROM kb_category ORDER BY id;

-- 基线备份表：回滚时按「不在备份表里的 id」删除，最稳
CREATE TABLE kb_knowledge_bak_20261118 AS SELECT * FROM kb_knowledge;
SELECT COUNT(*) AS bak_rows FROM kb_knowledge_bak_20261118;
```

> 备份表名里的日期按实际导入日改，后面回滚语句要对应修改。

### 2.2 确认 Milvus 集合维度是 1024

三个层面依次确认，任一层不对就先别导入：

**① 看服务配置（最直接）**

```bash
# ticket-knowledge 的配置里，embedding 维度必须是 1024
kubectl -n ai-tims get deploy ticket-knowledge -o yaml | grep -iE 'EMBED|dimensions'
kubectl -n ai-tims get cm -o yaml | grep -iE 'dimensions|embedding' | head -20
```

对应代码默认值：`tims.kb.milvus.collection=kb_knowledge_vec`、`tims.kb.embedding.dimensions=1024`
（`MilvusVectorStore.java` 第 49-53 行、`application.yml` 第 83、77 行）。

**② 看 Milvus 集合实际维度**

```bash
# 任一台能连 Milvus 的机器（或临时 pod）上执行，需要 pymilvus
python3 - <<'PY'
from pymilvus import connections, Collection
connections.connect(host="<milvus-host>", port="19530")
c = Collection("kb_knowledge_vec")
print("dim =", [f.params.get("dim") for f in c.schema.fields if f.name == "embedding"])
print("num_entities =", c.num_entities)
PY
```

期望 `dim = [1024]`。初始化脚本里没有建这个集合，它是服务启动后**惰性创建**的
（`MilvusVectorStore.java` 第 34、116 行），所以「先有一条知识被向量化成功」就说明维度是对的。

**③ 反向验证（出问题会报在这里）**

维度不对时，同步日志会出现 `[vector-sync] 本轮同步失败`，报 `dimension mismatch` 之类错误，Milvus 里不会写入。

> ⚠️ Qwen3-Embedding-8B 默认输出 **4096 维**，必须让 ticket-knowledge 显式请求 `dimensions=1024`
> （Matryoshka 降维），并且 vLLM 服务端支持该参数。这一条不满足，321 条一条都写不进 Milvus。

### 2.3 关于两边都有的 `kb_category`

`kb_category` 只有主键 `id`，没有唯一键（建表脚本第 155-166 行）。如果公司库已经存在同 id 的分类，
直接执行分类那段会报 `1062 Duplicate entry`，并且在 Navicat 里如果开了“遇错停止”，**后面的知识就不会导入**。

两种处理，二选一：

- **推荐**：导入时**只执行 `INSERT INTO \`kb_knowledge\`` 那一条语句**，跳过分类。`category_id` 也只是弱关联（无外键），分类可以在页面上手工建几条。
- 或者：先 `DELETE FROM kb_category WHERE id IN (...)` 清掉冲突分类（先 SELECT 确认、并留备份），再整包执行。

---

## 3. 执行导入

1. Navicat 连接到公司库，**先手动执行 `USE aitims;`**（导出的 SQL 里没有 `USE` 语句，不选库会报 "No database selected"）。
2. 打开 `kb_migrate_YYYYmmdd.sql`，按 2.3 的结论决定整包跑还是只跑 `kb_knowledge` 那条 `INSERT`。
3. 执行完看影响行数：`kb_knowledge` 那条应为 **320**。
4. **这个包只能导一次**。重复执行会因主键 `id` 冲突报 1062（不会产生重复数据，但也不会更新内容）。

> 现有那条 `id=2122940268192731138` 的测试知识不会被覆盖：导出用的是 `--complete-insert`，没有 `REPLACE`，
> 且它是公司库本地生成的 id，和开发机 320 条的 id 不冲突。

---

## 4. 导入后必做三步

### 4.1 关键一步：把迁移进来的行的向量同步标记置空

```sql
-- 推荐：只清迁移进来的行，保留公司原有测试知识的向量状态
UPDATE kb_knowledge
SET vector_synced_at = NULL
WHERE id <> 2122940268192731138;

-- 如果确实想全表重算（会把那条测试知识也重算，Milvus 里可能出现同一 id 的重复向量，不建议）
-- UPDATE kb_knowledge SET vector_synced_at = NULL;
```

为什么必须做：定时任务只扫 `PUBLISHED AND (vector_synced_at IS NULL OR update_time > vector_synced_at)`
（`VectorSyncService.java` 第 47-53 行）。开发机导过来的 318 条 PUBLISHED 都带着旧的 `vector_synced_at`，
不清就永远不会重算，检索会一条都命中不了。

### 4.2 核对总条数

```sql
SELECT COUNT(*) AS total FROM kb_knowledge;   -- 期望 321
```

### 4.3 按状态分组核对

```sql
SELECT status, COUNT(*) AS cnt FROM kb_knowledge GROUP BY status;
-- 期望：PUBLISHED 319、PENDING 2
```

> 完整的 7 项校验（含设备类型分布、随机抽样、创建人分布）直接执行 `docs/sql/kb_migrate_verify.sql`。

### 4.4（可选）回填创建人

```sql
-- 只想先把 NULL 的补成 1（admin）
UPDATE kb_knowledge SET create_by = 1 WHERE create_by IS NULL;
```

不做也没关系：列表不按创建人过滤，只是「创建人」列显示为空。

---

## 5. 确认向量化在干活

向量化由 `ticket-knowledge` 的定时任务完成：每 10 秒一轮、每批最多 16 条、先处理 `update_time` 最早的
（`VectorSyncService.java` 第 31-32、42、53 行）。320 条 ÷ 16 ≈ 20 轮。

### 5.1 看日志

```bash
kubectl -n ai-tims get pods | grep ticket-knowledge

# 实际日志前缀是 [vector-sync]（不是 [kb-sync]）
kubectl -n ai-tims logs -f <上面查到的 pod 名> | grep --line-buffered '\[vector-sync\]'
```

- 正常：每 10 秒左右出现一行 `[vector-sync] 同步 16 条知识进 Milvus`，最后变成 8 条收尾。
- 失败：出现 `[vector-sync] 本轮同步失败，下轮重试: ...`，按报错处理（多半是 embedding 地址/维度/鉴权）。
- 一行都没有：说明 `embeddingService.isConfigured()` 为 false（没配 key / 地址），任务会静默跳过（第 44-46 行）。

### 5.2 看 Milvus

```bash
python3 - <<'PY'
from pymilvus import connections, Collection
connections.connect(host="<milvus-host>", port="19530")
c = Collection("kb_knowledge_vec")
c.flush()
print("num_entities =", c.num_entities)
PY
```

期望最终 ≈ 321（含原有那 1 条）。`num_entities` 有延迟，刚写入时先 `flush()` 再查；
`upsert` 的实现是「先按主键删再插」（`MilvusVectorStore.java` 第 119 行），所以重复跑不会导致条数暴涨。

### 5.3 端到端确认

在页面上用一条明显的故障关键词搜（例如「吸嘴堵塞」「蚀刻速率偏低」），能命中并看到正文与设备类型，说明向量化 + 检索都通了。

**预期耗时**：20 轮 × 10 秒 ≈ 200 秒，加上每批 embedding 调用时间，整体约 **3~6 分钟**；
若 vLLM 排队或文本较长，最慢按 10 分钟估。期间不要重启 `ticket-knowledge`。

---

## 6. 回滚（不可逆，务必先 SELECT）

前提：第 2.1 步已经建了 `kb_knowledge_bak_20261118`（只含导入前的那 1 条）。

```sql
-- 6.1 先看要删多少、删哪些（只读，先看清楚）
SELECT COUNT(*) AS to_delete
FROM kb_knowledge
WHERE id NOT IN (SELECT id FROM kb_knowledge_bak_20261118);

SELECT id, title, status, create_time
FROM kb_knowledge
WHERE id NOT IN (SELECT id FROM kb_knowledge_bak_20261118)
LIMIT 20;

-- 6.2 确认无误后再删（不可逆）
DELETE FROM kb_knowledge
WHERE id NOT IN (SELECT id FROM kb_knowledge_bak_20261118);

-- 6.3 复核：应回到导入前的 1 条
SELECT COUNT(*) FROM kb_knowledge;
```

没有备份表时的备选（按 id 区间，**必须先 SELECT 看清范围**）：

```sql
-- 开发机雪花 id 与公司本地 id 一般落在不同区段；先确认边界
SELECT MIN(id), MAX(id), COUNT(*) FROM kb_knowledge
WHERE id <> 2122940268192731138;

SELECT COUNT(*) FROM kb_knowledge
WHERE id BETWEEN <最小id> AND <最大id> AND id <> 2122940268192731138;

-- 确认后才执行
DELETE FROM kb_knowledge
WHERE id BETWEEN <最小id> AND <最大id> AND id <> 2122940268192731138;
```

> **注意 `create_time` 不能用来判断“导入时间”**：`--complete-insert` 保留了开发机原始 `create_time`，
> 导入到公司库后这个字段还是 10 月/11 月初的时间。要按“导入批次”回滚，只能用备份表或 id 区间。

### 6.4 别忘了 Milvus 里的向量

删 MySQL 的行**不会**自动删 Milvus 里的向量，会留下“孤儿向量”（检索还能命中已删除的知识）。
两种处理：

1. 有按主键删除的封装：按上面删掉的 id 列表在 Milvus 侧 `delete(expr="knowledge_id in [...]")`，
   然后 `flush()`。
2. 没有封装（最稳）：清空集合 `kb_knowledge_vec`，再把 `kb_knowledge.vector_synced_at` 全部置空，
   让定时任务重建（顺序必须是“先清集合、再重置标记”）。

回滚完成后，建议再跑一次 `docs/sql/kb_migrate_verify.sql` 确认总数回到 1。

---

## 7. 一句话总结顺序

导出（开发机）→ 核对 md5 → 传文件 → Navicat 里 `USE aitims` + 建备份表 → 只跑 `kb_knowledge` 的 INSERT
→ 置空 `vector_synced_at` → 核对 321 / 319 / 2 → 看 `[vector-sync]` 日志跑完 → 看 Milvus 约 321 条
→ 页面搜一条验证。
