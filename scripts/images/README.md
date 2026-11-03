# scripts/images/ - 离线镜像交付工具

公司内网集群不出外网、公司 registry 外部不可达，因此走
**VM 构建 → docker save → 人工搬运（U盘/内网摆渡）→ 公司内 docker load → tag → push 公司仓库**。

## 文件

| 文件 | 执行位置 | 作用 |
|---|---|---|
| `images.env` | 两端共用 | 版本号 `APP_VERSION`、仓库前缀 `REGISTRY_PREFIX` 等唯一配置入口 |
| `build-images.sh` | VM | Maven 打包 + 构建 6 后端 + 1 前端镜像（`--platform linux/amd64`） |
| `save-images.sh` | VM | 业务镜像 + JRE/nginx 基础镜像一起 `docker save` 成 tar + sha256 |
| `load-images.sh` | 公司内网 | sha256 校验 + `docker load` + 自动 tag 到 `REGISTRY_PREFIX` |
| `push-images.sh` | 公司内网 | 逐镜像 push，失败打印镜像名与错误原文 |

## 最短路径

```bash
# ===== VM 侧 =====
cd ~/ai-tims/scripts/images
vim images.env                # 改 APP_VERSION
./build-images.sh             # 全量构建
./save-images.sh              # 产出 ~/image-delivery/tims-images-<版本>.tar(.sha256)
# 拷贝 tar + tar.sha256 + load-images.sh + push-images.sh + images.env 到 U盘

# ===== 公司内网侧 =====
vim images.env                # 填 REGISTRY_PREFIX=公司仓库地址/tims
./load-images.sh ./tims-images-<版本>.tar
docker login <公司仓库>
./push-images.sh
```

详细步骤、预期输出、失败判读见 `docs/ops/镜像离线交付手册.md`。

## 硬性约定

- 所有构建/save 显式 `--platform linux/amd64`（集群架构）
- 禁止 `latest` tag，版本号只在 `images.env` 改一处
- 基础镜像（JRE、nginx）已包含在 tar 中，公司侧 `load` 后不依赖外网
