# AI-TIMS k3s 单节点搭建手册（亲手执行版）

> **环境**：VM `ubuntu-server`（192.168.40.10，Ubuntu Server 22.04.5，4 vCPU / 16G / 根分区 96G LVM），已装 Docker 29.1.3 与本地镜像仓库 `localhost:5000`（`tims-registry` 容器），VM 可用宿主机 Clash 代理 `http://192.168.40.1:7897`。
>
> **定位与排期**：DEVLOG 拍板——VM k3s 单节点搭建在开题后（寒假）执行，任务书硬验收只需 k3s 单节点；预算约 8.5G/16G 内存（含精简监控）。本手册按「一条命令 → 预期输出 → 判断标准 → 失败怎么读报错」编写，照着敲即可。
>
> **诚实声明**：k3s 在写本文时尚未在 VM 上实际安装过，手册中的安装/排错命令基于 k3s 官方文档与本机已知环境写成；标注「需现场确认」处请在执行时以实际输出为准，遇到手册没写的现象先查 `journalctl -u k3s` 再补录 DEVLOG。

---

## 0. 与已有 Docker 共存：先记住这几条（最重要的前置认知）

1. **k3s 自带 embedded containerd，不用 Docker**。装 k3s 不会动你的 Docker，但两边镜像互不可见：`docker images` 里的镜像 k3s 看不到，必须经 registry（见第 6 节）。看 k3s 侧容器用 `sudo k3s crictl ps`，不是 `docker ps`。
2. **不要为 k3s 再装 Docker / kubeadm**。kubeadm 单节点比 k3s 多 ~1.5-2G 控制面开销，VM 上不推荐（DEVLOG 2026-11-02 结论）。
3. **不要重复装 ingress-nginx**。k3s 自带 Traefik；任务书口径是 VM 单节点验证 + 公司集群 namespace 部署，VM 上不需要第二套 ingress。若不需要可 `--disable traefik`。
4. **端口红线**：k3s server 要占 `6443`（apiserver）；Traefik 若启用占 `80/443`；还有 `10250`（kubelet）。装前逐一检查（第 1 步）。
5. **Docker 的 daemon.json 加速源对 k3s 无效**——containerd 不读 Docker 配置。k3s 拉镜像走第 6 节的 `registries.yaml` 或镜像前缀。

---

## 阶段一：前置检查（5 分钟，全绿再往下走）

### 1.1 端口空闲检查

```bash
ss -lntp | grep -E ':(6443|80|443|10250)\b' || echo "PORTS FREE"
```

- **预期输出**：`PORTS FREE`
- **判断标准**：四端口全部无监听。任何一行输出都是一个冲突源。
- **失败时**：输出里第一列进程名就是占用者。历史上 8080 曾被 tomcat9 占用（DEVLOG 2026-11-02，已 disable）；若 80/443 被占而暂不需要 Traefik，安装时加 `--disable traefik` 绕开；6443 被占通常是旧 k3s 未卸干净，先执行第 9 节卸载脚本。

### 1.2 内核模块

```bash
sudo modprobe overlay br_netfilter && lsmod | grep -E 'overlay|br_netfilter'
```

- **预期输出**：两行，`overlay` 与 `br_netfilter` 各一行。
- **判断标准**：两个模块都在列表里。
- **失败时**：`modprobe: FATAL: Module ... not found` 说明内核太精简——VM 用的是 Ubuntu 22.04 标准内核，一般不会缺；真缺则检查 `uname -r` 与 `linux-modules-extra` 包。

### 1.3 cgroup 版本

```bash
stat -fc %T /sys/fs/cgroup/
```

- **预期输出**：`cgroup2fs`（v2）或 `tmpfs`（v1）。
- **判断标准**：两者 k3s 都支持，只需记录是哪个，排障时报错措辞不同（v2 报 `cgroup controllers` 相关，v1 报 `subsystem` 相关）。
- **失败时**：无需处理，仅记录。

### 1.4 swap（kubelet 硬要求）

```bash
swapon --show && free -h | grep -i swap
```

- **预期输出**：`swapon --show` 无输出（Ubuntu Server 默认无 swap）；`free -h` 里 Swap 行为 0B。
- **判断标准**：swap = 0。
- **失败时**：若非 0：`sudo swapoff -a` 临时关，再编辑 `/etc/fstab` 注释 swap 行永久关。不关的后果：节点 NotReady，`journalctl -u k3s` 里有 kubelet 报 `running with swap on` 类错误。

### 1.5 防火墙

```bash
sudo ufw status
```

- **预期输出**：`Status: inactive`（22.04 默认）。
- **判断标准**：inactive 即可继续。
- **失败时**：若用户开过 ufw，要么 `sudo ufw allow 6443,10250/tcp && sudo ufw allow 8472/udp`（8472 是 flannel VXLAN），要么单机实验环境直接 `sudo ufw disable`。开着防火墙却没放行端口的典型症状：节点 NotReady / Pod 间不通。

### 1.6 磁盘余量

```bash
df -h /
```

- **预期输出**：根分区（96G LVM）Use% 明显低于 80%。
- **判断标准**：剩余 ≥10G（k3s 二进制 + airgap 镜像包 + containerd 镜像缓存都很占空间）。
- **失败时**：先 `docker system df` 看 Docker 占用，清理无用镜像/卷（**清理前对照文档一 5.2 节红线卷，别误删 `tims-*` 正本卷**）。

### 1.7 内存余量

```bash
free -h
```

- **预期输出**：available ≥ 8G（DEVLOG 预算 k3s 全家桶 ≈8.5G/16G，若还要跑全套中间件 + 应用，建议先把非必需容器停掉分时使用——4 vCPU 是瓶颈，DEVLOG 拍板「编译/压测/推理不同时段争核」）。
- **判断标准**：available 足够；不够就先 `docker stop tims-milvus tims-etcd tims-minio` 之类腾内存（用完 `docker start` 恢复）。

---

## 阶段二：安装（三选一）

### 2.1 方式 A：国内镜像源在线安装（首选，无需代理）

```bash
curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn sh -s - --write-kubeconfig-mode 644
```

- **预期输出**：脚本依次下载 k3s 二进制与 kubectl/kubelet 链接，结尾输出 `[INFO] Created ... k3s.service` 类日志，无 ERROR。
- **判断标准**：命令退出码 0，且 `sudo systemctl status k3s` 显示 active（下一阶段验证）。
- **说明**：`INSTALL_K3S_MIRROR=cn` 使二进制从 `rancher-mirror.rancher.cn` 下载，国内直连可用，**不需要代理**。`--write-kubeconfig-mode 644` 让非 root 用户能读 kubeconfig（单机实验可接受，生产不要这么开）。
- **失败时**：curl 报 000/超时 → 网络问题，试方式 B；脚本中途报下载失败 → 看是哪个 URL 失败，该 URL 手动 `wget` 复测定位。

### 2.2 方式 B：走宿主机代理安装（镜像源失效时备用）

```bash
export http_proxy=http://192.168.40.1:7897 https_proxy=http://192.168.40.1:7897
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
unset http_proxy https_proxy
```

- **预期输出**：同方式 A。
- **判断标准**：同方式 A。
- **失败时**：000 超时先确认宿主机 Clash 已开且 **Allow LAN 生效**（DEVLOG 记过：7897 曾只绑 127.0.0.1，需重启 Clash 内核使 0.0.0.0:7897 生效）。VM 里验证通道：`curl -x http://192.168.40.1:7897 -sfL https://get.k3s.io -o /dev/null -w '%{http_code}\n'`，预期 200。

### 2.3 方式 C：离线安装（无网兜底）

在宿主机（走 Clash）下载三个文件，scp 到 VM：

```bash
# 宿主机执行（版本号以 rancher-mirror 上的最新 stable 为准，需现场确认）
curl -LO https://rancher-mirror.rancher.cn/k3s/k3s-install.sh
curl -LO https://rancher-mirror.rancher.cn/k3s/k3s-linux-amd64        # 下载后改名 k3s
curl -LO https://rancher-mirror.rancher.cn/k3s/k3s-airgap-images-amd64.tar.zst
scp k3s-install.sh k3s k3s-airgap-images-amd64.tar.zst ubuntu-server:~/k3s-offline/
```

VM 上执行：

```bash
sudo mkdir -p /var/lib/rancher/k3s/agent/images/
sudo cp ~/k3s-offline/k3s-airgap-images-amd64.tar.zst /var/lib/rancher/k3s/agent/images/
sudo chmod +x ~/k3s-offline/k3s && sudo cp ~/k3s-offline/k3s /usr/local/bin/
INSTALL_K3S_SKIP_DOWNLOAD=true sh ~/k3s-offline/k3s-install.sh --write-kubeconfig-mode 644
```

- **预期输出**：脚本跳过下载直接安装，结尾 `[INFO] ... k3s.service`。
- **判断标准**：同方式 A。镜像包会在 k3s 首次启动时由 containerd 自动导入。
- **失败时**：`systemctl status k3s` 起不来且日志报镜像相关 → 确认 images 包放在上述目录且扩展名 `.tar.zst` 未被改；报二进制不可执行 → 检查架构 `uname -m` 应为 x86_64。

---

## 阶段三：验证安装（每条都是硬判据）

### 3.1 节点 Ready

```bash
sudo k3s kubectl get nodes -o wide
```

- **预期输出**：一行，`STATUS` 为 `Ready`，VERSION 是 k3s 版本号。
- **判断标准**：`Ready` 才算过；`NotReady` 说明 CNI/网络层没起。
- **失败时**：`NotReady` → `journalctl -u k3s --no-pager | tail -50`，搜 `flannel`、`cni`、`network`；常见原因是 1.5 节防火墙没放行或 iptables 异常（对照第 8 节对照表）。

### 3.2 版本信息

```bash
sudo k3s --version
```

- **预期输出**：`k3s version <vX.Y.Z+k3s1> ... go1.x` 两行。
- **判断标准**：能打印版本即二进制完好。记录版本号进 DEVLOG（**需现场确认**实际安装的版本）。

### 3.3 systemd 服务状态

```bash
systemctl status k3s --no-pager
```

- **预期输出**：`Active: active (running)`，主进程为 `/usr/local/bin/k3s server`。
- **判断标准**：active (running) 且重启过 VM 后仍自启（k3s 安装脚本默认 enable）。
- **失败时**：`failed`/`activating` → `journalctl -u k3s -e --no-pager` 看最后 20 行，报错关键通常在最后一段。

### 3.4 非 root kubectl 可用（顺带配置）

```bash
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config && sudo chown $USER:$USER ~/.kube/config
kubectl get nodes
```

- **预期输出**：与 3.1 相同的节点列表，但无需 sudo。
- **判断标准**：`kubectl get nodes` 返回 Ready。
- **失败时**：`connection refused :6443` → kubeconfig 里 server 地址是 127.0.0.1 就应该通，若被改成了主机名/IP 则改回 `https://127.0.0.1:6443`（单机本地使用场景）。

---

## 阶段四：跑第一个 Pod（理解成败原因）

### 4.1 起一个 Pod

```bash
kubectl run lab-nginx --image=docker.m.daocloud.io/library/nginx:alpine
kubectl get pod lab-nginx -w
```

（第二条 Ctrl+C 退出观察。）

- **预期输出**：`CONTAINERING → Running`，几十秒内 `READY 1/1`。
- **判断标准**：`STATUS=Running`。
- **为什么它会成功**：k3s 的 containerd 直接按完整镜像地址 `docker.m.daocloud.io/library/nginx:alpine` 拉取——daocloud 对 `library/*` 官方镜像有缓存（DEVLOG 实证：403 只发生在 `milvusdb/*` 这类小众命名空间），且 containerd 的拉取动作发生在宿主机网络命名空间，VM 直连 daocloud 是通的。
- **失败时怎么读报错**：`STATUS=ImagePullBackOff/ErrImagePull` → `kubectl describe pod lab-nginx`，**只看 Events 段最后一条 `Failed to pull image ...`**，里面写了真实原因（超时/403/manifest unknown/网络不通）。注意：给 shell 设 `http_proxy` 环境变量对 containerd **无效**（见第 8 节对照表第 5 行）。

### 4.2 看它实际跑在哪

```bash
sudo k3s crictl ps
```

- **预期输出**：能看到 lab-nginx 的容器（ID 前缀 + 镜像名），与 `docker ps` **列表不同**。
- **判断标准**：能找到该容器，理解「k3s 用自己的 containerd，与 Docker 并存互不可见」这一共存核心事实。

```bash
kubectl delete pod lab-nginx    # 练完即删
```

---

## 阶段五：用本地 registry（localhost:5000）的镜像跑 Pod

### 5.1 先把镜像推进本地仓库（Docker 侧操作）

```bash
docker pull redis:7-alpine
docker tag redis:7-alpine localhost:5000/tims/redis:lab
docker push localhost:5000/tims/redis:lab
curl -sf http://localhost:5000/v2/_catalog     # 预期可见 "tims/redis"
```

- **预期输出**：push 成功输出 digest；catalog 返回 `{"repositories":["tims/redis",...]}`。
- **判断标准**：与文档一 4.3 相同的推拉闭环判据（此流程 DEVLOG 已实测过，digest 一致性核对见该节）。
- **失败时**：push 报 `connection refused :5000` → `docker ps | grep tims-registry` 确认 registry 容器在跑。

### 5.2 告诉 k3s 的 containerd 这个私有仓库是 HTTP

```bash
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  localhost:5000:
    endpoint:
      - "http://localhost:5000"
EOF
sudo systemctl restart k3s
```

- **预期输出**：tee 无输出；restart 后 `systemctl is-active k3s` 返回 `active`。
- **判断标准**：k3s 重启后仍 active（约 10-30 秒恢复），节点仍 Ready。
- **为什么需要这个文件**：containerd 默认按 HTTPS 访问非 localhost 仓库；对 `localhost:5000` 部分版本也会按 Docker 惯例走 HTTP，但**显式写 registries.yaml 最稳**（各版本行为差异 **需现场确认**：若不写也能拉，说明该版本 containerd 沿用了 localhost insecure 惯例，文件保留作显式声明）。
- **为什么 Pod 里访问不到 localhost:5000 也无妨**：镜像拉取由宿主机上的 containerd 执行（宿主机 localhost:5000 就是 registry 容器映射的端口），拉取成功后镜像已在本地，Pod 运行时不需要再访问 registry。
- **失败时**：restart 后 k3s 起不来 → `journalctl -u k3s -e`，多半是 YAML 缩进错（`mirrors:` 下两层缩进照抄即可）。

### 5.3 用仓库里的镜像起 Pod

```bash
kubectl run lab-redis --image=localhost:5000/tims/redis:lab
kubectl get pod lab-nginx lab-redis 2>/dev/null; kubectl get pod lab-redis
```

- **预期输出**：`lab-redis` 状态 `Running`（数秒级，因为镜像已在节点本地）。
- **判断标准**：Running。
- **失败时**：ImagePullBackOff → describe 看 Events：`http: server gave HTTP response to HTTPS client` = registries.yaml 没生效（检查缩进、确认 restart 过）；`connection refused` = registry 容器没跑。

### 5.4 理解 imagePullPolicy（本阶段核心知识点）

```bash
kubectl explain pod.spec.containers.imagePullPolicy | head -20
```

三条规则（答辩常问）：

| 镜像 tag | 默认策略 | 效果 |
|---|---|---|
| `:latest` 或无 tag | `Always` | 每次调度都试图去 registry 比对，本地有也可能重拉 |
| 明确版本 tag（如 `:lab`） | `IfNotPresent` | 本地有就直接用——**本地 registry + 单节点方案的地基**（compose 正本注释与 DEVLOG tag 规则约定的依据） |
| 任意 + 显式声明 | 按声明 | 显式写 `imagePullPolicy: Always/IfNotPresent/Never` |

**IfNotPresent 的坑**：更新代码重新 push 同名同 tag 镜像后，Pod 不会自动用新镜像（本地有旧的）。对策：tag 带版本/时间戳（`localhost:5000/tims/system:20261220a`），这也解释了 tag 规则里 `{ver}` 的意义。

```bash
kubectl delete pod lab-redis    # 练完即删
```

---

## 阶段六：截图留痕点（按仓库既有规范）

仓库已建截图规范：`docs/screenshots/`，命名 `日期_阶段_内容.png`（见 `docs/screenshots/README.md` 与 DEVLOG 第七节）。VM 无 GUI，截图方式：把命令输出存文件后在本机对终端/文件截图，或直接保存输出文本 + 终端截图。

| 序号 | 拍什么 | 命令 | 建议文件名 |
|---|---|---|---|
| 1 | 节点 Ready | `kubectl get nodes -o wide` | `2026MMDD_k3s_nodes_ready.png` |
| 2 | 版本与服务 | `k3s --version` + `systemctl status k3s --no-pager` 同屏 | `2026MMDD_k3s_version_systemd.png` |
| 3 | 第一个 Pod | `kubectl get pod lab-nginx`（Running） | `2026MMDD_k3s_first_pod.png` |
| 4 | 本地仓库镜像 Pod | `kubectl get pod lab-redis` + `k3s crictl images \| grep localhost:5000` | `2026MMDD_k3s_registry_image_pod.png` |
| 5 | 拉取事件证据 | `kubectl describe pod lab-redis` 的 Events 段（出现 pulled `localhost:5000/...`） | `2026MMDD_k3s_pullevent_local_reg.png` |
| 6 | （若遇失败）报错现场 | `kubectl describe pod ...` Events + `journalctl -u k3s -e` 尾部 | `2026MMDD_k3s_fail_<现象>.png` |

存放到仓库 `/home/dev/ai-tims/docs/screenshots/`，文件名日期以实际执行日为准。

---

## 阶段七：常见失败对照表

| # | 症状 | 一眼定位 | 根因 | 处理 |
|---|---|---|---|---|
| 1 | 安装报 `6443 ... address already in use` 或装完 apiserver 连不上 | `ss -lntp \| grep 6443` | 6443 被占（旧 k3s 残留 / 其他组件） | 找到占用进程：旧 k3s → 跑卸载脚本（第 9 节）；其他进程 → 停掉或改用其空闲环境 |
| 2 | 节点 NotReady，`journalctl -u k3s` 有 swap 字样 | `free -h \| grep -i swap` | swap 未关，kubelet 拒绝工作 | `sudo swapoff -a` + 清 `/etc/fstab` swap 行后 `sudo systemctl restart k3s` |
| 3 | 节点 NotReady，Pod 全部 Pending，日志有 iptables/CNI 报错 | `sudo ufw status`；`journalctl -u k3s \| grep -iE 'flannel\|cni\|iptables'` | 防火墙拦 VXLAN(8472/udp) 或 iptables 规则异常 | ufw 放行 6443/10250/tcp、8472/udp 或实验机直接 disable；iptables 混乱时 `sudo systemctl restart k3s` 让其重建规则 |
| 4 | Traefik 起不来或 80/443 冲突，`kubectl get pods -n kube-system` 里 traefik 反复重启 | `ss -lntp \| grep -E ':80\|:443'` | 宿主机已有服务占 80/443 | 确认不需要 ingress 就安装时加 `--disable traefik`；需要则停掉占用进程（不要装 ingress-nginx 替代，重复） |
| 5 | 镜像拉取超时，shell 里 `curl` 却通 | describe pod 的 `Failed to pull image ... i/o timeout` | **containerd 不继承 shell 的 http_proxy 环境变量**，也不读 Docker 的 daemon.json | 要么用国内直连镜像前缀（daocloud 等）；要么给 k3s 配代理：写入 `/etc/systemd/system/k3s.service.env`（`HTTP_PROXY=http://192.168.40.1:7897`、`HTTPS_PROXY=...`、`NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,192.168.0.0/16`，**NO_PROXY 必须含 localhost:5000 网段**，否则本地仓库拉取也会被送去代理），然后 `sudo systemctl daemon-reload && sudo systemctl restart k3s` |
| 6 | `kubectl` 报 `The connection to the server localhost:8080 was refused` | `echo $KUBECONFIG`；`ls ~/.kube/config` | kubeconfig 未配置/未拷贝 | 按 3.4 拷贝配置，或 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml`（配合 644 权限） |
| 7 | VM 重启后 k3s 没起来 | `systemctl status k3s` | 安装脚本默认 enable，一般不会发生；若被手动 disable | `sudo systemctl enable --now k3s`（参照 DEVLOG：Docker 也曾因 VM 重启后未自启踩坑，已 `enable docker`） |

---

## 阶段八：卸载与清理

```bash
# 一条命令完整卸载 k3s（server 端；含 service、二进制、containerd 数据、CNI/iptables 清理）
sudo /usr/local/bin/k3s-uninstall.sh
```

- **预期输出**：一串清理日志，结尾无报错。
- **验证卸载干净**：

```bash
kubectl get nodes 2>&1 | head -1        # 预期 connection refused（kubectl 还在但服务没了）
ls /var/lib/rancher 2>&1                # 预期 No such file or directory
ss -lntp | grep -E ':(6443|10250)'      # 预期无输出
```

- **残留处理**：极少数情况 iptables 规则残留导致 Docker 网络异常 → `sudo reboot`（最省事）；脚本 `k3s-killall.sh` 也在 `/usr/local/bin/` 可用于强制清进程。
- **不会被删的**：Docker 及其全部容器/卷（含 `tims-registry` 与 `localhost:5000` 里的镜像）——卸载 k3s 不碰 Docker 侧任何东西，这正是共存设计的方便之处。
- 卸载后若要重装，直接回到阶段二，`registries.yaml` 需重新写入（在 /etc/rancher 下，卸载会删）。

---

## 附：执行完本手册后，往 DEVLOG 里记什么（台账制度要求）

1. 实际安装方式（A/B/C）与 k3s 版本号（3.2 输出）；
2. 前置检查各项实际值（尤其 cgroup 版本、内存余量）；
3. 第一个 Pod / 本地镜像 Pod 的实测现象，与手册预期不符处（补录为踩坑条目）；
4. 截图文件名清单（对应第七节表格）。
