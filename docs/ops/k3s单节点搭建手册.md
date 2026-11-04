# AI-TIMS k3s 单节点搭建手册（亲手执行版）

> **环境**：VM `ubuntu-server`（192.168.40.10，Ubuntu Server 22.04.5，**内核 5.15.0-202-generic**——由旧版本升级而来，不是 24.04 默认的 6.8），4 vCPU / 15Gi 内存 / 根分区 96G LVM（实测已用 25%），**swap 4G（`/swap.img`）**，已装 Docker 29.1.3 与本地镜像仓库 `localhost:5000`（`tims-registry` 容器），VM 可用宿主机 Clash 代理 `http://192.168.40.1:7897`。**【实测 2026-11-04】k3s 已安装：v1.36.5+k3s1，节点 `zzqserver` Ready，`k3s.service active (running)`；swap 仍为 4G 未关（见 1.4 方案 A）；系统组件镜像须经宿主机代理才能拉取，已在 `/etc/systemd/system/k3s.service.env` 配 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`（见 3.7），**重装脚本会重置该文件（见 3.8，最容易复发）**。**
>
> **定位与排期**：DEVLOG 拍板——VM k3s 单节点搭建在开题后（寒假）执行，任务书硬验收只需 k3s 单节点；预算约 8.5G/16G 内存（含精简监控）。本手册按「一条命令 → 预期输出 → 判断标准 → 失败怎么读报错」编写，照着敲即可。
>
> **标注体系（重要）**：本文分两类内容——
> - **纸面推导**：写手册时（2026-11-03）VM 尚未装过 k3s，命令与判据基于 k3s 官方文档与本机已知环境推演，标注「需现场确认」处请以实际输出为准；
> - **实测确认（2026-11-04）**：用户按本手册走阶段一前置检查时实际执行所得，已就地补进对应小节并标 `【实测】`，汇总见文末「实测记录（2026-11-04）」。
>
> **复制命令注意**：只复制代码块内的命令，**不要连 Markdown 的反引号一起复制**。反引号在 shell 中是命令替换，实测踩过：把 `` `代码` `` 整段粘进终端会报 `NO_BRIDGE_SYSCTL: command not found`、`1: command not found`（反引号内的词被当作命令执行了）。

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

### 1.2 内核模块（含四级验证与持久化）

**【实测】先记住最大的坑：`modprobe` 一次只加载一个模块。** `sudo modprobe overlay br_netfilter` 的效果是——加载 `overlay`，并试图把 `br_netfilter` 当成 **overlay 的模块参数**传进去，结果 `lsmod` 只见 `overlay`，`br_netfilter` 永远不出现。必须分两条：

```bash
sudo modprobe overlay
sudo modprobe br_netfilter
# 或者：sudo modprobe overlay && sudo modprobe br_netfilter
```

- **现象**：`lsmod | grep br_netfilter` 无输出，且 `cat /proc/sys/net/bridge/bridge-nf-call-iptables` 报 `No such file or directory`。
- **原因**：`modprobe` 的语法是 `modprobe <模块名> [模块参数...]`，空格后的第二个词是参数不是模块。
- **正确做法**：一条一个模块，逐条验证。**实测：单独执行 `modprobe br_netfilter` 后，`lsmod` 立即出现该模块，`bridge` 的引用计数由 0 变 1，sysctl 值为 1。**

**四级验证（从弱到强，手册原来只写了 `lsmod | grep`）**：

```bash
lsmod | grep br_netfilter                  # ① 可加载模块方式（加载后才有）
ls -d /sys/module/br_netfilter              # ② built-in 或已加载都会出现该目录（更宽松）
grep br_netfilter /proc/modules             # ③ 运行内核的模块清单
modinfo br_netfilter | head -5              # ④ 确认 ko 属于「当前运行内核」
uname -r                                    # 与上一条 filename 里的版本对照
```

- **预期输出**：①③ 各一行 `br_netfilter ... Live ...`；②输出 `/sys/module/br_netfilter`；④`filename: /lib/modules/5.15.0-202-generic/kernel/net/bridge/br_netfilter.ko`，其版本段必须等于 `uname -r`。
- **判断标准（唯一硬判据）**：

```bash
cat /proc/sys/net/bridge/bridge-nf-call-iptables     # 预期 1
```

该文件**只有在 br_netfilter 加载后才存在**，能读出 `1` 即表示模块生效且桥接流量已交给 iptables——比 `lsmod` 更可靠（`lsmod` 会有残留/别名干扰）。

**模块持久化（`modprobe` 重启即失效，必须写文件）**：

```bash
sudo tee /etc/modules-load.d/k3s.conf >/dev/null <<'EOF'
overlay
br_netfilter
EOF
```

- **为什么必须**：这台 VM 此前已多次重启；不写这个文件会出现经典的「**装的时候好好的、重启后 k3s 起不来**」（k3s 起来后 overlay 缺失 → containerd 报 snapshotter 错误，br_netfilter 缺失 → CNI 桥接规则不生效、Pod 网络不通）。
- **验证**：`sudo reboot` 后重跑上面四级验证，仍应为 `1`。

**sysctl 三项（k3s 网络前提）**：

```bash
sudo tee /etc/sysctl.d/99-k3s.conf >/dev/null <<'EOF'
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system
```

- **预期输出**：大量 `* Applying ...`，最后三行包含上面三项。
- **【实测】可忽略的两条噪音**：`net.ipv4.conf.all.accept_source_route` 与 `net.ipv4.conf.all.promote_secondaries` 会报 `Invalid argument`——这是镜像内既有 sysctl 配置与 5.15 内核版本不匹配导致的，**与 k3s 无关**，不用处理。
- **判断标准**：只核对三条 `= 1`：

```bash
sysctl net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables net.ipv4.ip_forward
```

- **失败时**：若三项仍为 0 或文件不存在 → 回到上一段确认 `br_netfilter` 真加载了（`bridge-nf-call-*` 依赖它）；`ip_forward = 1` 不生效 → 检查是否有 `sysctl.d` 里后续文件覆盖（`grep -r ip_forward /etc/sysctl.d /etc/sysctl.conf`）。

### 1.3 cgroup 版本

```bash
stat -fc %T /sys/fs/cgroup/
```

- **预期输出**：`cgroup2fs`（v2）或 `tmpfs`（v1）。
- **判断标准**：两者 k3s 都支持，只需记录是哪个，排障时报错措辞不同（v2 报 `cgroup controllers` 相关，v1 报 `subsystem` 相关）。
- **失败时**：无需处理，仅记录。

### 1.4 swap（不是「必须关」，分 k3s 版本看）

```bash
swapon --show && free -h | grep -i swap
```

- **预期输出**：`swapon --show` 无输出（Ubuntu Server 默认无 swap）；`free -h` 里 Swap 行为 0B。
- **【实测】本 VM 不是默认零 swap**：存在 **4G 的 `/swap.img`**（此前为应对 Milvus 内存压力开过），实测占用仅 780K。
- **【实测 2026-11-04】保留 swap 也装成功了**：未执行 `swapoff`，直接按阶段二安装（只加 `--write-kubeconfig-mode 644`，未加任何 `fail-swap-on` 参数），结果 k3s **v1.36.5+k3s1**、节点 `zzqserver` **Ready**、`k3s.service active (running)`。**因此「开着 swap 必然 NotReady」在 v1.36.x 上不成立。**

**三方案对照（按你的 k3s 版本选）**：

| 方案 | 适用版本 | 做法 | 代价/收益 |
|---|---|---|---|
| **A. 保留 swap（推荐本机）** | **k3s ≥ 1.28，实测 v1.36.5 默认不拦** | 什么都不用改，直接装 | 收益：给 Milvus 三件套留 OOM 兜底（本机 4G swap）；代价：kubelet 的内存驱逐判断偏乐观——可能先走 swap 再驱逐，表现为「变慢但不重启」 |
| B. 关掉 swap | 任何版本都适用 | `sudo swapoff -a`，并把 `/etc/fstab` 里 `/swap.img` 那行注释掉（否则重启又回来） | 收益：驱逐判断最准；代价：Milvus 无兜底、OOM 直接杀容器 |
| C. 老版本放行 | **k3s < 1.28**（kubelet 默认硬拦） | 安装时加 `--kubelet-arg=fail-swap-on=false`，或按 B 关掉 | 不加参数会报 `running with swap on is not supported`，节点 NotReady |

- **判断标准**：装完后 `kubectl get nodes` 为 `Ready` 即通过——**无论 swap 开或关**。不要拿 `swapon --show` 是否有输出反过来判定安装成败（实测证明二者无必然关系）。
- **失败时**：若确实 NotReady 且 `journalctl -u k3s` 出现 `running with swap on is not supported`（只可能出现在老版本或显式 `--kubelet-arg=fail-swap-on=true` 时），按方案 B 关 swap 或方案 C 加参数后 `sudo systemctl restart k3s`。
- **本机建议**：走**方案 A**（保留 4G swap），配合 1.7「装前停 Milvus」策略；单节点演示场景下「变慢但不重启」的代价可接受。

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

- **预期输出**：**【实测】** 全中间件在跑（Docker + Nacos + Milvus 三件套 + RabbitMQ + registry + 6 个 Java 服务）时 `used 5.7G / available 9.5G`（总 15Gi）。
- **判断标准**：available ≥ 8G 可装；6~8G 之间建议先腾；<6G 必须腾。
- **【实测】怎么腾内存（原来只写了预算，没写实际操作）**：优先停 Milvus 三件套（三容器限额合计 2G、实测峰值 1.5G 左右，是最大的可回收项），且它们与 k3s 控制面争的是同一批内存：

```bash
# 装 k3s 前
docker stop tims-milvus tims-etcd tims-minio
free -h                                  # 确认 available 上去了
# 装完且节点 Ready 后恢复
docker start tims-etcd tims-minio tims-milvus   # 顺序：etcd/minio 先，milvus 后
```

  > ⚠ 停 Milvus 期间 `ticket-knowledge` 的向量检索会走降级（纯关键词，返回体带 fallback 标记）——这是设计好的降级路径，属预期，不是故障。恢复启动后健康检查约 1~2 分钟。
  > ⚠ 不要停 Nacos/MySQL/网关等业务必需组件；也不要停 `tims-registry`（阶段五要用它）。
- **失败时**：腾完仍不够 → `docker stats --no-stream` 找真正的大户，再考虑分时段（DEVLOG 已拍板「编译/压测/推理不同时段争核」，4 vCPU 是瓶颈）。

---

## 阶段二：安装（三选一）

### 2.1 方式 A：国内镜像源在线安装（首选，无需代理）

```bash
curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn sh -s - --write-kubeconfig-mode 644
```

- **预期输出**：脚本依次下载 k3s 二进制与 kubectl/kubelet 链接，结尾输出 `[INFO] Created ... k3s.service` 类日志，无 ERROR。
- **判断标准**：命令退出码 0，且 `sudo systemctl status k3s` 显示 active（下一阶段验证）。
- **说明**：`INSTALL_K3S_MIRROR=cn` 使 k3s **二进制与安装脚本**从 `rancher-mirror.rancher.cn` 下载，国内直连可用，**不需要代理**。`--write-kubeconfig-mode 644` 让非 root 用户能读 kubeconfig（单机实验可接受，生产不要这么开）。
- **⚠ 关键认知（实测 3 小时 48 分卡住的根因）**：`INSTALL_K3S_MIRROR=cn` **只加速二进制和脚本，不加速系统镜像**——`rancher/mirrored-pause`、`coredns`、`traefik` 等系统镜像仍从 `docker.io` 拉取。国内环境**必须**为 k3s 的 containerd 配代理（见 3.7）或改用 `registries.yaml` 镜像源，否则节点虽 `Ready`、系统 Pod 会全部卡在 `ContainerCreating`。
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
- **失败时**：`connection refused :6443` → kubeconfig 里 server 地址是 127.0.0.1 就应该通，若被改成了主机名/IP 则改回 `https://127.0.0.1:6443`（单机本地使用场景）。`The connection to the server localhost:8080 was refused` → 没读到 kubeconfig（对照第 8 节表第 6 行）。

### 3.5 三条验证命令（一次看全，装完必跑）

```bash
kubectl get nodes -o wide                          # ① 节点
kubectl get pods -A                                # ② 全 namespace 的 Pod
systemctl status k3s --no-pager | head -5          # ③ 服务状态
```

- **① 预期**：一行，`STATUS=Ready`，`INTERNAL-IP` 为本机地址，`VERSION` 形如 `v1.31.x+k3s1`（具体版本 **需现场确认**）。判断标准：`Ready`。
- **② 预期**：`kube-system` 下出现 `traefik`（1 个）、`coredns`（1 个）、`local-path-provisioner`（1 个）、`metrics-server`（1 个）、`svclb-traefik`（2 个，DaemonSet 每节点一个），全部 `Running`；`helm-install-*` 两个 Job 显示 `Completed`。判断标准：**上述 Pod 全部 Running**——它们是 k3s 默认自带组件的「活着」的证明（Traefik 没起通常是 80/443 被占，见第 8 节表第 4 行；CoreDNS 没起通常是节点 NotReady 连带）。**【实测】首次安装时这批 Pod 全部卡 `ContainerCreating` 长达 3 小时 48 分，原因是系统镜像拉 docker.io 失败，修复后约 4 分钟内全部 Running**（见 3.7）。
- **③ 预期**：`Active: active (running)`，`Loaded: ... enabled`（enabled 表示重启自启已开）。
- **失败时**：先看 ③ 的 `Active:` 行；`activating (start)` 卡住超过 1 分钟 → `journalctl -u k3s -e --no-pager | tail -30`，按最后一段报错对应第 8 节表格。

### 3.6 为什么 `docker images` 里看不到 k3s 的镜像（别误判「镜像丢了」）

- **现象**：装完 k3s 后 `docker ps` / `docker images` 里**看不到** k3s 侧的容器与镜像；反过来 `kubectl` 也看不到 `tims-*` 那批 Docker 容器。
- **原因**：k3s 用**自带的 embedded containerd**，与系统 Docker 是两套完全独立的运行时和镜像存储（`/var/lib/rancher/k3s/agent/containerd` vs `/var/lib/docker`）。两者并存但**镜像互不可见**。
- **正确做法**：查 k3s 侧用 `sudo k3s crictl ps` / `sudo k3s crictl images`；要让 k3s 用到本地仓库里的镜像，必须走阶段五的 `registries.yaml` + `localhost:5000` 显式地址——**不能指望 containerd 自动“看见”Docker 的本地镜像**。
- **判断标准**：`sudo k3s crictl images` 能看到 `rancher/*` 等系统镜像、却看不到 `tims/*`（在推送到 registry 之前）→ 这就是正常现象，不是丢镜像。

### 3.7 【实测必读】系统组件卡 `ContainerCreating`：给 k3s 的 containerd 配代理

**实测现象（2026-11-04）**：k3s 装完、节点 `Ready`、`k3s.service active (running)`，但 `kubectl get pods -A` 里所有系统 Pod 全部卡在 `ContainerCreating`，**持续 3 小时 48 分**它们也不会自己好。

**怎么读错（三步定位）**：

```bash
kubectl get pods -A
kubectl describe pod -n kube-system <卡住的 pod 名> | tail -20   # 看 Events 段
```

Events 里出现 **`FailedCreatePodSandBox`**，进一步信息是 `Failed to create pod sandbox: ... failed to get sandbox image "rancher/mirrored-pause:3.10.2": ... docker.io ... connection refused`——即 **pause 镜像从 `docker.io` 拉不下来**（实测反复重试 79 次）。`pause` 镜像是起任何 Pod sandbox 的前提，它拉不到，所有 Pod 就永远 `ContainerCreating`。

**根因**：k3s 的 containerd **不继承 shell 的 `http_proxy`，也不读 Docker 的 `daemon.json`**（见第 8 节表第 5 行）；而 `INSTALL_K3S_MIRROR=cn` 只加速二进制与安装脚本（见 2.1），系统镜像仍直连 `docker.io`。

**修复（实测有效，约 4 分钟全部恢复）**：

```bash
sudo tee /etc/systemd/system/k3s.service.env >/dev/null <<'EOF'
HTTP_PROXY=http://192.168.40.1:7897
HTTPS_PROXY=http://192.168.40.1:7897
NO_PROXY=127.0.0.1,localhost,192.168.40.0/24,10.42.0.0/16,10.43.0.0/16
EOF
sudo systemctl daemon-reload
sudo systemctl restart k3s
kubectl get pods -n kube-system            # 等 1~2 分钟看状态变化
kubectl delete pod -n kube-system --all    # 卡住的 Pod 不会自己重试成功，删掉让控制器重建
```

- **`NO_PROXY` 为什么必须含这些网段**：`10.42.0.0/16` 是 Pod CIDR、`10.43.0.0/16` 是 Service CIDR、`192.168.40.0/24` 含本机与 `localhost:5000` 本地仓库——不排除这些，集群内部流量和本地仓库拉取也会被送去代理，反而更糟。
- **预期结果（实测）**：约 4 分钟内 `coredns`、`local-path-provisioner`、`metrics-server`、`traefik`、`svclb-traefik` 全部 `Running`，两个 `helm-install-*` 转 `Completed`。
- **判断标准**：`kubectl get pods -n kube-system` 里无 `ContainerCreating` 残留。
- **失败时**：仍 `ContainerCreating` → 再看 `describe` 的 Events；若报 `connection refused` 到代理端口 → 先在本机确认 Clash 的 **Allow LAN** 生效（`curl -x http://192.168.40.1:7897 -sfL https://get.k3s.io -o /dev/null -w '%{http_code}\n'` 应为 200）；若报 `ImagePullBackOff` 且镜像地址是 `docker.io` → 代理没生效，`systemctl show k3s | grep -i proxy` 复查环境变量是否被服务读到。

### 3.8 【重要】安装脚本会重建 `k3s.service.env`——代理配置被清空

**这是最容易复发的一条。** k3s 安装脚本**每次执行都会重新生成** `/etc/systemd/system/k3s.service.env`（安装日志里的 `env: Creating environment file ...` 就是它），因此 3.7 里追加的 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY` **会被整体覆盖清空**。

- **实测经过**：当天重跑一次安装脚本后该文件被重置。此时**镜像已被缓存，系统 Pod 仍然 Running**——问题被完美掩盖，看起来「一切正常」，**直到下次需要拉一个新镜像时才会再次失败**。
- **重装/升级后的必做检查**：

```bash
cat /etc/systemd/system/k3s.service.env | grep -i proxy    # 有输出才算没丢
```

- **丢了就补**：重新执行 3.7 的 `tee` 写入 → `sudo systemctl daemon-reload && sudo systemctl restart k3s`。
- **判断标准**：重装后 `kubectl run` 一个**本地没有的新镜像**（如 `kubectl run probe --image=docker.m.daocloud.io/library/nginx:alpine`）能 `Running`，才算代理链路真的在；只看已有 Pod 还绿着**不能**证明（见上条「被缓存掩盖」）。
- **结论**：凡是跑过安装脚本（包括升级、重装、改动安装参数），**立刻复查本文件**，不要等拉镜像失败才发现。

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
- **【实测 2026-11-04】**：`docker push localhost:5000/tims/redis:lab` 成功，digest 前缀 **`1cf73a2f`**；`curl -sf http://localhost:5000/v2/_catalog` 返回含 **`tims/redis`** 与 **`tims/ticket-push`**（后者为业务镜像，说明仓库里已有交付用镜像）。
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
- **【实测 2026-11-04】**：按 5.2 写入 `registries.yaml` 并重启 k3s 后，`kubectl run lab-redis --image=localhost:5000/tims/redis:lab` **成功 Running**；练完即删（镜像仍在 k3s 侧 containerd 里，便于复跑）。
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
| 0 | **前置检查全绿**（开题材料用图）：端口空闲 + `cgroup2fs` + swap 现状（4G 开着也算过）+ 磁盘/内存 + `bridge-nf-call-iptables=1` 同屏 | 阶段一 1.1~1.7 各命令连续执行 | `2026MMDD_k3s_precheck_all_green.png` |
| 1 | 节点 Ready（开题材料用图） | `kubectl get nodes -o wide` | `2026MMDD_k3s_nodes_ready.png` |
| 2 | 版本与服务 | `k3s --version` + `systemctl status k3s --no-pager` 同屏 | `2026MMDD_k3s_version_systemd.png` |
| 3 | 第一个 Pod | `kubectl get pod lab-nginx`（Running） | `2026MMDD_k3s_first_pod.png` |
| 4 | 本地仓库镜像 Pod | `kubectl get pod lab-redis` + `k3s crictl images \| grep localhost:5000` | `2026MMDD_k3s_registry_image_pod.png` |
| 5 | 拉取事件证据 | `kubectl describe pod lab-redis` 的 Events 段（出现 pulled `localhost:5000/...`） | `2026MMDD_k3s_pullevent_local_reg.png` |
| 6 | （若遇失败）报错现场 | `kubectl describe pod ...` Events + `journalctl -u k3s -e` 尾部 | `2026MMDD_k3s_fail_<现象>.png` |
| 7 | **系统组件全 Running + 代理配置同屏**（证明 3.7 的修复生效，答辩可讲排障） | `kubectl get pods -n kube-system` + `cat /etc/systemd/system/k3s.service.env` | `2026MMDD_k3s_syspods_proxy.png` |

存放到仓库 `/home/dev/ai-tims/docs/screenshots/`，文件名日期以实际执行日为准。

---

## 阶段七：常见失败对照表

| # | 症状 | 一眼定位 | 根因 | 处理 |
|---|---|---|---|---|
| 1 | 安装报 `6443 ... address already in use` 或装完 apiserver 连不上 | `ss -lntp \| grep 6443` | 6443 被占（旧 k3s 残留 / 其他组件） | 找到占用进程：旧 k3s → 跑卸载脚本（第 9 节）；其他进程 → 停掉或改用其空闲环境 |
| 2 | 节点 NotReady，`journalctl -u k3s` 出现 `running with swap on is not supported` | `free -h \| grep -i swap`；`k3s --version` | **仅老版本（k3s < 1.28）**：kubelet 默认硬拦 swap；v1.36.x 默认不拦（2026-11-04 实测未关 swap 仍 Ready） | 老版本：`sudo swapoff -a` + 注释 `/etc/fstab` swap 行，或安装参数 `--kubelet-arg=fail-swap-on=false`，然后 `sudo systemctl restart k3s`（见 1.4） |
| 3 | 节点 NotReady，Pod 全部 Pending，日志有 iptables/CNI 报错 | `sudo ufw status`；`journalctl -u k3s \| grep -iE 'flannel\|cni\|iptables'` | 防火墙拦 VXLAN(8472/udp) 或 iptables 规则异常 | ufw 放行 6443/10250/tcp、8472/udp 或实验机直接 disable；iptables 混乱时 `sudo systemctl restart k3s` 让其重建规则 |
| 4 | Traefik 起不来或 80/443 冲突，`kubectl get pods -n kube-system` 里 traefik 反复重启 | `ss -lntp \| grep -E ':80\|:443'` | 宿主机已有服务占 80/443 | 确认不需要 ingress 就安装时加 `--disable traefik`；需要则停掉占用进程（不要装 ingress-nginx 替代，重复） |
| 5 | **系统 Pod 全部卡 `ContainerCreating`**，describe 报 `FailedCreatePodSandBox` + `rancher/mirrored-pause ... docker.io ... connection refused` | `kubectl describe pod -n kube-system <pod> \| tail -20`；`cat /etc/systemd/system/k3s.service.env` | **containerd 不继承 shell 的 `http_proxy`**，也不读 Docker 的 `daemon.json`；`INSTALL_K3S_MIRROR=cn` 只加速二进制，系统镜像仍走 `docker.io` | 写入 `/etc/systemd/system/k3s.service.env`（`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY=127.0.0.1,localhost,192.168.40.0/24,10.42.0.0/16,10.43.0.0/16`），`daemon-reload` + `restart k3s` + `delete pod -n kube-system --all`（实测约 4 分钟全部 Running，见 3.7） |
| 6 | `kubectl` 报 `The connection to the server localhost:8080 was refused` | `echo $KUBECONFIG`；`ls ~/.kube/config` | kubeconfig 未配置/未拷贝 | 按 3.4 拷贝配置，或 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml`（配合 644 权限） |
| 7 | VM 重启后 k3s 没起来 | `systemctl status k3s` | 安装脚本默认 enable，一般不会发生；若被手动 disable | `sudo systemctl enable --now k3s`（参照 DEVLOG：Docker 也曾因 VM 重启后未自启踩坑，已 `enable docker`） |
| 8 | **只加载上一个模块**：`lsmod \| grep -E 'overlay\|br_netfilter'` 只见 `overlay`，`br_netfilter` 一直不出现 | `lsmod \| grep br_netfilter`；`cat /proc/sys/net/bridge/bridge-nf-call-iptables`（报 No such file） | **`modprobe overlay br_netfilter` 把第二个词当成了模块参数**，不是加载第二个模块 | 分成两条：`sudo modprobe overlay`、`sudo modprobe br_netfilter`；再写 `/etc/modules-load.d/k3s.conf`（见 1.2） |
| 9 | `sysctl --system` 报两条 `Invalid argument`：`net.ipv4.conf.all.accept_source_route`、`net.ipv4.conf.all.promote_secondaries` | 报错里的键名 | 镜像内既有 sysctl 配置与 5.15 内核版本不匹配，**与 k3s 无关** | 忽略这两行；只核对 `bridge-nf-call-iptables/-ip6tables`、`ip_forward` 三项为 1（见 1.2） |
| 10 | 终端报 `NO_BRIDGE_SYSCTL: command not found` 或 `1: command not found` | 报错里被当命令执行的词 | **复制命令时带上了 Markdown 反引号**，反引号被 shell 当作命令替换 | 去掉反引号重敲；习惯上只复制代码块内文本（见文首「复制命令注意」） |
| 11 | 装完 `docker images` / `docker ps` 看不到 k3s 的镜像与容器，误以为「镜像丢了」 | `sudo k3s crictl images` | k3s 用自带 containerd，与 Docker 镜像存储完全独立，互不可见 | 属正常现象；要让 k3s 用本地仓库镜像须配 `registries.yaml` + `localhost:5000`（见 3.6 与阶段五） |
| 12 | **装的时候正常、重启后 k3s 起不来**，日志里 containerd/CNI 报错 | `uname -r`；`lsmod \| grep -E 'overlay\|br_netfilter'` | 模块只在内存里 `modprobe` 过，重启后未自动加载 | 写 `/etc/modules-load.d/k3s.conf`（内容 `overlay`、`br_netfilter`）后 `sudo systemctl restart k3s`（见 1.2） |
| 13 | 排查时发现「忘了 `swapoff`」，但节点明明 Ready | `swapon --show`；`k3s --version`；`kubectl get nodes` | **新版 k3s（≥1.28，实测 v1.36.5）默认允许 swap，Ready 属正常行为**，不是故障 | **不要往 swap 方向排查**（也不用补关）：只有节点 NotReady 且日志明确报 `running with swap on is not supported` 才处理（见 1.4 三方案） |
| 14 | **重装/升级 k3s 后新镜像又拉不动，但旧 Pod 仍全绿**（极易误判「已经好了」） | `cat /etc/systemd/system/k3s.service.env \| grep -i proxy`（无输出即丢失） | **安装脚本每次都重建 `k3s.service.env`**（日志有 `env: Creating environment file ...`），3.7 追加的代理配置被清空；已缓存镜像掩盖了问题 | 重新追加 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY` → `daemon-reload` + `restart k3s`；用「本地没有的新镜像」起 Pod 验证，而不是看旧 Pod（见 3.8） |

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

## 实测记录（2026-11-04）：前置检查 → 安装 → 排障 → 本地仓库打通（全过程）

> **性质**：以下为**真实实装记录**（用户按本手册在 VM 上执行），与上文「纸面推导」部分严格区分。实测机型：Ubuntu Server 22.04.5，内核 **5.15.0-202-generic**（旧版本升级而来，非 24.04 默认 6.8），4 vCPU / 15Gi，根分区 96G（已用 23G）。

| 检查项 | 手册小节 | 实测结果 | 判定 |
|---|---|---|---|
| 端口 6443/80/443/10250 | 1.1 | 全部空闲（`PORTS FREE`） | ✅ 过 |
| 内核模块 | 1.2 | `overlay` 已加载；`br_netfilter` 起初未加载（`modprobe` 语法误用），单独加载后 `lsmod` 出现、`bridge` 引用计数 0→1、`/proc/sys/net/bridge/bridge-nf-call-iptables` = 1 | ✅ 过（经排障） |
| cgroup | 1.3 | `cgroup2fs`（v2） | ✅ 过 |
| swap | 1.4 | **4G `/swap.img`**（与手册「预期 0」不符），实测仅用 780K；**未关 swap 直接安装，节点仍 Ready** | ✅ 过（保留 swap，按 1.4 方案 A） |
| 防火墙 | 1.5 | `ufw` inactive | ✅ 过 |
| 磁盘 | 1.6 | 根分区 96G，已用 23G（约 25%），可用约 69G | ✅ 过（远超 ≥10G 门槛） |
| 内存 | 1.7 | `used 5.7G`、`available 9.5G`（全中间件 + 6 服务在跑） | ✅ 可装；按 1.7 建议装前先停 Milvus 三件套 |
| **安装结果** | 阶段二 | `--write-kubeconfig-mode 644`，**未加 `fail-swap-on`、未执行 `swapoff`** → **k3s v1.36.5+k3s1**；节点 `zzqserver` **Ready**；`k3s.service active (running)` | ✅ 通过（同时修正 1.4 的旧结论） |
| sysctl | 1.2 | 三项均 1；`sysctl --system` 有两行 `Invalid argument` 噪音（与 k3s 无关） | ✅ 过（噪音忽略） |
| **系统 Pod（首次）** | 3.5 / 3.7 | 全部卡 `ContainerCreating`，**持续 3 小时 48 分**；`describe` 报 `FailedCreatePodSandBox`，根因 `rancher/mirrored-pause:3.10.2` 从 `docker.io` 拉取 `connection refused`，**重试 79 次** | ❌ 故障（见 3.7 修复） |
| **系统 Pod（修复后）** | 3.7 | 配 `/etc/systemd/system/k3s.service.env` 代理 → `daemon-reload` + `restart k3s` + `delete pod -n kube-system --all` → **约 4 分钟内全部 Running**：`coredns`、`local-path-provisioner`、`metrics-server`、`traefik`、`svclb-traefik`；两个 `helm-install-*` 转 `Completed` | ✅ 过 |
| **资源占用（装后）** | 1.7 | k3s 服务内存 **1.4G**；系统 `available 9.8G` | ✅ 充裕（预算 8.5G/16G 内） |
| **本地 registry 打通** | 5.1~5.3 | `docker tag redis:7-alpine localhost:5000/tims/redis:lab` → push digest **`1cf73a2f…`**；`_catalog` 含 **`tims/redis`、`tims/ticket-push`**；写 `/etc/rancher/k3s/registries.yaml`（mirror → `http://localhost:5000`）→ 重启 k3s → `kubectl run lab-redis --image=localhost:5000/tims/redis:lab` **Running**，练完即删 | ✅ 过 |
| **重跑安装脚本** | 3.8 | 重跑一次安装脚本后 `/etc/systemd/system/k3s.service.env` **被重建，代理配置被清空**；因镜像已缓存，系统 Pod 仍 Running，问题被掩盖 | ⚠ 复发隐患（见 3.8 / 表第 14 行） |

**本次最关键的两个真坑**：

1. **`sudo modprobe overlay br_netfilter` 只加载了 `overlay`**——第二个词被当作模块参数。根因与正确做法见 1.2 / 表第 8 行；同时暴露「模块未持久化」的隐患（重启后失效），已补 `/etc/modules-load.d/k3s.conf` 要求。
2. **系统镜像不走镜像源、必须配 containerd 代理**——卡 `ContainerCreating` 3 小时 48 分才定位到 `FailedCreatePodSandBox` / pause 镜像 `docker.io` 拉取失败（79 次重试）。修复见 3.7；而**安装脚本每次重跑都会重置 `k3s.service.env` 把代理抹掉**，且被缓存镜像掩盖，见 3.8 / 表第 14 行。

**装前待办的实际进展**：① VMware 快照——**需现场确认是否已拍**（若未拍，现在补拍并记名）；② ~~停 Milvus 腾内存 + swapoff~~ → **实测未关 swap 也装成功**，swap 按 1.4 方案 A 保留即可（Milvus 停止与否以 `free -h` available ≥8G 为准）；③ 安装——**已完成（v1.36.5+k3s1，节点 Ready）**；④ 写 `registries.yaml` 并跑阶段四/五——**已完成（本地仓库镜像 Pod 已 Running）**；⑤ 截图（见阶段六与 DEVLOG 第七节）——**待办**（含 `2026MMDD_k3s_precheck_all_green.png`、`2026MMDD_k3s_nodes_ready.png`、系统 Pod 全 Running 与代理配置同屏）。

---

## 附：执行完本手册后，往 DEVLOG 里记什么（台账制度要求）

1. 实际安装方式（A/B/C）与 k3s 版本号（3.2 输出）；
2. 前置检查各项实际值（尤其 cgroup 版本、内存余量）；
3. 第一个 Pod / 本地镜像 Pod 的实测现象，与手册预期不符处（补录为踩坑条目）；
4. 截图文件名清单（对应第七节表格）。
