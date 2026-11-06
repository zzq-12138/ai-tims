# AI-TIMS Kubernetes 交付物（公司集群 v1.24.17）

本目录所有内容按 **Kubernetes v1.24.17 / containerd 1.6.24** 编写。
本地 k3s **v1.36.5+k3s1** 只能证明「跑得通」，**不能**作为 1.24 兼容证据。

- 兼容自检：[docs/ops/K8s-1.24-兼容自检.md](../docs/ops/K8s-1.24-兼容自检.md)
- 公司侧准入核查：[docs/ops/公司集群准入核查清单.md](../docs/ops/公司集群准入核查清单.md)

## 1. 目录结构

```text
deploy/
├── docker/Dockerfile                 # 六服务共用运行镜像（JRE17 + 非 root 10001）
├── k8s/
│   ├── base/                         # kustomize base（1.24 兼容基线）
│   │   ├── namespace.yaml
│   │   ├── resourcequota.yaml
│   │   ├── limitrange.yaml
│   │   ├── config/common-configmap.yaml
│   │   ├── secret.example.yaml       # 仅模板，不在 kustomization 中
│   │   ├── middleware/
│   │   │   ├── mysql.yaml
│   │   │   ├── mysql/init-job.yaml   # 单独 apply，不在默认资源里
│   │   │   ├── redis.yaml
│   │   │   ├── rabbitmq.yaml
│   │   │   ├── nacos.yaml
│   │   │   └── milvus.yaml           # etcd + minio + milvus
│   │   ├── apps/
│   │   │   ├── gateway.yaml  system.yaml  order.yaml
│   │   │   ├── knowledge.yaml  ai.yaml  push.yaml
│   │   └── ingress.yaml
│   └── overlays/company/kustomization.yaml   # 公司仓库/镜像 tag 覆盖入口
└── scripts/
    ├── images.env                    # 镜像清单唯一版本来源（禁止 latest）
    ├── build-images.sh               # VM 执行
    ├── save-images.sh                # VM 执行
    ├── load-and-push.sh              # 公司侧能访问仓库的机器执行
    └── validate-manifests.sh         # 渲染 + 1.24 静态校验
```

## 2. 端口实际口径（已核对仓库 application.yml）

| 服务 | 仓库实际端口 | 任务书旧口径 | K8s Service |
|---|---|---|---|
| ticket-gateway | 8080 | 8080 | 8080 |
| ticket-system | **8101** | 8081 | 8101 |
| ticket-order | **8102** | 8082 | 8102 |
| ticket-knowledge | **8103** | 8083 | 8103 |
| ticket-ai | 8104 | 8104 | 8104 |
| ticket-push | 8105 | 8105 | 8105 |

中间件：MySQL 3306、Redis 6379、RabbitMQ 5672/15672、Nacos 8848/9848/9849、Milvus 19530/9091、etcd 2379、MinIO 9000/9001。

## 3. 离线镜像链路（四条命令）

> 原则：VM 负责构建，公司集群只负责 `docker load` 和 push；集群内 Pod 不下载任何依赖。

```bash
# ① VM：编译 + 构建六个业务镜像
bash deploy/scripts/build-images.sh

# ② VM：拉齐中间件镜像，docker save 单 tar，并生成/校验 sha256
bash deploy/scripts/save-images.sh
# 产物：deploy/dist/tims-images-1.0.0.tar / .tar.sha256 / images-1.0.0.txt

# ③ 公司侧（能访问公司仓库的机器）：校验 sha256 -> load -> 重打 tag -> push
COMPANY_REGISTRY=harbor.公司域名 bash deploy/scripts/load-and-push.sh deploy/dist/tims-images-1.0.0.tar

# ④ VM 或公司侧有 kubectl/kubeconform 的机器：按 1.24.17 渲染 + 静态校验
bash deploy/scripts/validate-manifests.sh
```

每一步在哪做、失败怎么判：

| 步骤 | 执行位置 | 前置 | 失败现象 | 判定与处理 |
|---|---|---|---|---|
| ① build | VM | JDK17、Maven、Docker daemon | `mvn` 失败 / `未找到 ... JAR` | 先修 Maven 构建，不要继续 save |
| ② save | VM | ①成功；VM 可拉公网镜像 | `缺少业务镜像` / `docker pull` 失败 | 业务镜像回 ①；中间件镜像检查 VM 出口/镜像代理 |
| ② 校验 | VM | tar 生成 | `sha256sum -c` FAILED | 传输损坏，重新 save；不要带病交付 |
| ③ load/push | 公司侧 | Docker、仓库账号、网络可达 registry | `unauthorized` / `connection refused` | 找管理员确认仓库地址、项目与 push 权限 |
| ④ validate | 任意有工具机器 | kubectl/kubeconform | 命中黑名单 / schema 报错 | 改 manifest；没有工具时只能标「待公司验证」 |

## 4. 部署前必须创建的两类 Secret

`deploy/k8s/base/secret.example.yaml` 只是模板，**不包含在 kustomization 中**，不会被 `apply -k` 误创建。

```bash
# 4.0 先建命名空间（后面的 -n ai-tims 才有意义）
kubectl apply -f deploy/k8s/base/namespace.yaml

# 4.1 应用密钥（所有 REPLACE_ME 必须替换；禁止提交真实值）
kubectl -n ai-tims create secret generic tims-app-secret \
  --from-literal=MYSQL_ROOT_PASSWORD='...' \
  --from-literal=MYSQL_PASSWORD='...' \
  --from-literal=REDIS_PASSWORD='...' \
  --from-literal=RABBIT_PASSWORD='...' \
  --from-literal=RABBITMQ_ERLANG_COOKIE='...' \
  --from-literal=NACOS_AUTH_TOKEN="$(openssl rand -base64 32)" \
  --from-literal=NACOS_AUTH_IDENTITY_KEY=serverIdentity \
  --from-literal=NACOS_AUTH_IDENTITY_VALUE='...' \
  --from-literal=NACOS_PASSWORD='...' \
  --from-literal=MINIO_ROOT_USER='...' \
  --from-literal=MINIO_ROOT_PASSWORD='...' \
  --from-literal=LLM_API_KEY='...' \
  --from-literal=ZHIPU_API_KEY='...' \
  --from-literal=SMTP_AUTH='...'

# 4.2 镜像仓库拉取凭据（imagePullSecrets）
kubectl -n ai-tims create secret docker-registry tims-registry \
  --docker-server=harbor.公司域名 \
  --docker-username='<账号>' \
  --docker-password='<密码或 Token>'
```

Secret 与 Deployment 的关系：

- 所有业务 Pod 通过 `imagePullSecrets: [{name: tims-registry}]` 拉镜像。
- 数据库/Redis/Rabbit/Nacos/MinIO 密码只在对应中间件与需要它的服务中按 key 注入，不做整包 `envFrom`。
- Redis 密码同时以 `SPRING_DATA_REDIS_PASSWORD` 注入六服务（Spring Boot 宽松绑定到 `spring.data.redis.password`）。

## 5. 部署顺序

```bash
# 1) 先确认准入清单已回填，再改仓库地址/域名
#    deploy/k8s/overlays/company/kustomization.yaml  harbor.example.com
#    deploy/k8s/base/ingress.yaml                    tims.company.local / ingressClassName

# 2) 应用命名空间、配额、中间件、六服务、Ingress
kubectl apply -k deploy/k8s/overlays/company

# 3) 等中间件就绪（首次拉镜像会慢）
kubectl -n ai-tims rollout status statefulset/tims-mysql --timeout=10m
kubectl -n ai-tims rollout status statefulset/tims-redis --timeout=5m
kubectl -n ai-tims rollout status statefulset/tims-rabbitmq --timeout=5m
kubectl -n ai-tims rollout status statefulset/tims-nacos --timeout=10m
kubectl -n ai-tims rollout status deployment/tims-etcd --timeout=5m
kubectl -n ai-tims rollout status deployment/tims-minio --timeout=5m
kubectl -n ai-tims rollout status deployment/tims-milvus --timeout=10m

# 4) 首次初始化数据库（会 DROP/CREATE 表，只跑一次）
kubectl -n ai-tims create configmap tims-mysql-init \
  --from-file=init.sql=sql/init.sql --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/base/middleware/mysql/init-job.yaml
kubectl -n ai-tims logs -f job/tims-mysql-init

# 5) 六个服务
kubectl -n ai-tims rollout status deployment/ticket-system --timeout=10m
kubectl -n ai-tims rollout status deployment/ticket-order --timeout=10m
kubectl -n ai-tims rollout status deployment/ticket-knowledge --timeout=10m
kubectl -n ai-tims rollout status deployment/ticket-ai --timeout=10m
kubectl -n ai-tims rollout status deployment/ticket-push --timeout=10m
kubectl -n ai-tims rollout status deployment/ticket-gateway --timeout=10m

# 6) 不依赖 Ingress 的冒烟测试
kubectl -n ai-tims port-forward svc/ticket-gateway 18080:8080
curl -sS http://127.0.0.1:18080/actuator/health
```

## 6. 常见失败判定

| 现象 | 首查 | 处理 |
|---|---|---|
| `ImagePullBackOff`/`ErrImagePull` | `kubectl describe pod` 的 Events | 镜像是否已 push；`tims-registry` 是否在正确 namespace；仓库地址是否写错 |
| `Pending` | `kubectl describe pod` | ResourceQuota、StorageClass 不存在/无 PV、节点污点、requests 过大 |
| `CreateContainerConfigError` | `describe pod` | `tims-app-secret` 缺失或 key 名不一致 |
| `CrashLoopBackOff` | `kubectl logs --previous` | MySQL 密码/库名、Nacos 未就绪、Redis 密码不一致 |
| `Running` 但 `0/1 Ready` | `kubectl describe pod` 探针失败详情 | `/actuator/health/readiness` 是否 DOWN（DB/Redis/Nacos） |
| Ingress 404/502 | `kubectl describe ingress ai-tims` | `ingressClassName`、host、Service 端口、Ingress Controller 是否安装 |
| 首次建表失败 | `logs job/tims-mysql-init` | ConfigMap 是否含 `init.sql`；MySQL 是否 ready |
| knowledge/ai 调用超时 | Pod 内 DNS/出口 | 公司内网无外网，必须改 `LLM_BASE_URL`/`ZHIPU_EMBEDDING_URL` 或申请出口 |

## 7. 已知边界（交付时必须说明）

- **数据库名统一为 `aitims`**（与 `sql/init.sql`、各服务 `application.yml` 默认值一致）；根目录 `.env.example` 里的 `ai_tims` 是历史笔误，K8s 部署不使用该值。
- **六服务镜像未包含前端**：本目录只覆盖任务要求的后端六服务与中间件；前端如需部署另行出 Nginx 镜像/Ingress 规则。
- **Nacos 3 使用内嵌 derby**，数据落 PVC；毕设规模够用，不承诺高可用。
- **MySQL/Redis/RabbitMQ/Nacos/Milvus 均为单副本**，节点故障会中断；这是资源预算内的取舍。
- **公司内网不出外网**：`open.bigmodel.cn`（LLM/embedding）与 QQ SMTP 均不可达。未申请出口前，`ticket-knowledge` 的向量化与 `ticket-ai` 的模型调用会失败，`ticket-system` 已默认 `VERIFY_SENDER=mock`。
- **本目录未提交任何真实密码/账号**；`secret.example.yaml` 只有占位符。
