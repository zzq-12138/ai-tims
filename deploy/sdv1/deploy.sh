#!/usr/bin/env bash
# =============================================================================
# deploy.sh —— AI-TIMS 单服务/全量升版部署（公司 master1 上执行）
#
# 用法：
#   ./deploy.sh <service> <tag> [--force] [--yes]
#   ./deploy.sh --help
#
#   service: front | ai | gateway | knowledge | order | push | system | all
#   tag    : 镜像标签，例如 1.0.2
#
# 例：
#   ./deploy.sh front 1.0.2
#   ./deploy.sh all   1.0.1
#   EXPECTED_CONTEXT=kubernetes-admin@kubernetes ./deploy.sh order 1.0.2
#
# 设计说明（两条与“改 apps/*.yaml 的 image 行”不同的地方，务必先看）：
#   1) deploy/k8s/overlays/company/kustomization.yaml 里有 images: 段，
#      每个服务都有 newTag，kustomize 渲染时会用它覆盖 base 清单里的 image tag。
#      也就是说：只 sed base/apps/*.yaml 的 image 行是【不生效】的。
#      所以本脚本把 newTag 作为唯一生效入口来改，同时同步 base 清单的 image 行
#      （保持仓库可读、避免下次误以为清单没更新）。
#   2) 前端与后端走同一条路径：同样改 overlay 的 newTag，再同步 base/apps/front.yaml
#      的 image 行，最后 apply -k。
#      不再使用 kubectl set image（手工改集群会和清单脱钩，下一次 apply 就被带回）。
#
# 安全边界：
#   - 只操作当前 kube-context 下的 ai-tims 命名空间；
#   - 不写死任何密码 / token / Harbor 凭据；
#   - 所有被改动的文件都有 .bak，失败会自动还原并重新 apply；
#   - apply 前强制做一次渲染预检：打印全部 image 行与关键配置项，并与集群现状对比，
#     发现版本回退（如 1.0.1 -> 1.0.0）必须显式确认（交互输入 DOWNGRADE 或 --allow-downgrade）。
# =============================================================================
set -euo pipefail

NAMESPACE="ai-tims"

# 仓库根：从脚本所在目录逐级向上找含 deploy/k8s/overlays/company 的目录。
# 这样脚本放在 deploy/sdv1/、images/、或任何子目录都能跑。
find_repo_root() {
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [ "$d" != "/" ]; do
    if [ -d "$d/deploy/k8s/overlays/company" ]; then printf '%s\n' "$d"; return 0; fi
    d="$(dirname "$d")"
  done
  return 1
}

REPO_ROOT="$(find_repo_root)" || {
  printf '[ERROR] 找不到仓库根：从 %s 向上没有 deploy/k8s/overlays/company\n' \
    "$(dirname "${BASH_SOURCE[0]}")" >&2
  exit 1
}

OVERLAY_DIR="$REPO_ROOT/deploy/k8s/overlays/company"
OVERLAY_FILE="$OVERLAY_DIR/kustomization.yaml"
BASE_DIR="$REPO_ROOT/deploy/k8s/base"
APPS_DIR="$BASE_DIR/apps"
HARBOR_PREFIX="harbor.xnunion.com/library"
SRC_PREFIX="registry.company.internal/ai-tims"
# 镜像包目录：<仓库根>/images（可用环境变量 IMAGES_DIR 覆盖）
IMAGES_DIR="${IMAGES_DIR:-$REPO_ROOT/images}"

FORCE=0
ASSUME_YES=0
SKIP_IMAGE=0
ALLOW_DOWNGRADE=0
BAK_FILES=()
RENDER_TMP=""
cleanup_tmp() { [ -n "${RENDER_TMP:-}" ] && rm -f "$RENDER_TMP" "$RENDER_TMP.err"; }
trap cleanup_tmp EXIT

usage() {
  cat <<'USAGE'
AI-TIMS 部署脚本

用法:
  ./deploy.sh <service> <tag> [--force] [--yes]
  ./deploy.sh --help

service:
  front      前端 ai-tims-front（与后端同一路径：改 overlay 的 newTag + 同步 base + apply -k）
  ai         ticket-ai
  gateway    ticket-gateway
  knowledge  ticket-knowledge
  order      ticket-order
  push       ticket-push
  system     ticket-system
  all        6 个后端一次性升版（前端不含在 all 里，需单独执行）

tag:
  目标镜像标签，例如 1.0.2。镜像需已推送到 harbor.xnunion.com/library/<image>:<tag>

选项:
  --force             当前 kube-context 与 EXPECTED_CONTEXT 不一致时仍然继续
  --yes               跳过交互确认（git 工作区不干净时也不再询问；不豁免版本回退确认）
  --no-image          跳过镜像准备（不 load、不 push）；镜像已确认在 Harbor 上时用
  --allow-downgrade   预检发现版本回退时不再交互询问，直接继续（用于明确的回滚操作）

环境变量:
  EXPECTED_CONTEXT   期望的 kube-context 名；为空则不校验，只打印
                    例：EXPECTED_CONTEXT=kubernetes-admin@kubernetes ./deploy.sh order 1.0.2
  IMAGES_DIR         镜像包目录，默认 <仓库根>/images
                    包名规则：<镜像名>-<tag>.tar 或 .tar.gz
                    例：images/ai-tims-front-1.0.2.tar、images/ticket-ai-1.0.3.tar.gz

执行流程:
  1. 校验参数、打印 context / 命名空间 / 现有 Pod 数
  2. 检查 git 工作区（不干净只提示）
  3. 镜像准备：本机没有就从 IMAGES_DIR load；Harbor 上没有就 push
  4. 备份并改写清单：改 overlay 的 newTag，同时同步 base 的 image 行（前后端一致）
  5. 部署前预检：kubectl kustomize 渲染一次，打印全部 image 行与关键配置项，
     并与集群现状逐项对比；跨 ConfigMap 重复 key 会醒目告警；
     版本回退需显式确认，否则终止（不改集群）
  6. kubectl apply -k deploy/k8s/overlays/company
  7. 逐个 rollout status（180s 超时）；目标 tag 与当前一致时改为 rollout restart
  8. 回读实际镜像并打印新 Pod 名
  9. 任一步失败：自动用 .bak 还原并重新 apply，打印回滚后的 tag 与排错命令

回滚:
  单服务回到旧 tag（预检会打印每个服务 apply 前的集群 tag）:
    ./deploy.sh <service> <旧tag> --no-image --yes
  前端同理：overlay newTag 与 base/apps/front.yaml 会一起改回旧值再 apply -k。
  仅撤最近一次 Deployment 变更:
    kubectl -n ai-tims rollout undo deploy/<deployment>
  配置回滚: 修改或删除 deploy/k8s/overlays/company/patches/ 下对应行，
            再执行 kubectl apply -k deploy/k8s/overlays/company
USAGE
}

log()  { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die()  { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

# ---------- service 映射表（均已按仓库实际文件核对） ----------
# manifest: base 清单路径（前端也在 base/apps/front.yaml）
svc_manifest() {
  case "$1" in
    order)     echo "$APPS_DIR/order.yaml" ;;
    system)    echo "$APPS_DIR/system.yaml" ;;
    gateway)   echo "$APPS_DIR/gateway.yaml" ;;
    knowledge) echo "$APPS_DIR/knowledge.yaml" ;;
    ai)        echo "$APPS_DIR/ai.yaml" ;;
    push)      echo "$APPS_DIR/push.yaml" ;;
    front)     echo "$APPS_DIR/front.yaml" ;;
    *) return 1 ;;
  esac
}
# k8s Deployment 名称
svc_deploy() {
  case "$1" in
    front) echo "ai-tims-front" ;;
    all)   return 1 ;;
    *)     echo "ticket-$1" ;;
  esac
}
# Harbor 镜像全名（不含 tag）
svc_image() {
  case "$1" in
    front) echo "$HARBOR_PREFIX/ai-tims-front" ;;
    all)   return 1 ;;
    *)     echo "$HARBOR_PREFIX/ticket-$1" ;;
  esac
}
# base 清单里的原始镜像名（用于 sed 同步）
# 前端在 base 里本来就是 Harbor 全名，所以与 svc_image 相同。
svc_src_image() {
  case "$1" in
    front) echo "$HARBOR_PREFIX/ai-tims-front" ;;
    all)   return 1 ;;
    *)     echo "$SRC_PREFIX/ticket-$1" ;;
  esac
}

# ---------- 镜像准备：找包 -> load -> push ----------
# 在 IMAGES_DIR（默认 <仓库根>/images）里找：<base>-<tag>.tar[.gz] 或 <base>_<tag>.tar[.gz]
find_tar() {
  local base="$1" tag="$2" d f
  for d in "$IMAGES_DIR" "$REPO_ROOT/deploy/sdv1/images"; do
    [ -d "$d" ] || continue
    for f in "${base}-${tag}.tar" "${base}-${tag}.tar.gz" "${base}_${tag}.tar" "${base}_${tag}.tar.gz"; do
      if [ -f "$d/$f" ]; then printf '%s\n' "$d/$f"; return 0; fi
    done
  done
  return 1
}

# 本机没有该 tag 就 load；Harbor 上没有就 push（push 幂等，已存在的层会跳过）
ensure_image() {
  local svc="$1" tag="$2" img base tar
  img="$(svc_image "$svc"):$tag"
  base="$(basename "${img%:*}")"

  command -v docker >/dev/null 2>&1 || { warn "未找到 docker，跳过镜像准备：$img"; return 0; }

  if docker image inspect "$img" >/dev/null 2>&1; then
    log "  镜像已在本机：$img"
  else
    tar="$(find_tar "$base" "$tag" || true)"
    [ -n "$tar" ] || die "本机没有 $img，且 $IMAGES_DIR 下找不到 ${base}-${tag}.tar[.gz]（先把镜像包放进该目录）"
    log "  load  $tar"
    docker load -i "$tar" >/dev/null || die "docker load 失败：$tar"
    docker image inspect "$img" >/dev/null 2>&1 \
      || die "load 完成但本机仍无 $img；包里的 tag 可能不是 $tag，请用 docker images 核对"
  fi

  if docker manifest inspect "$img" >/dev/null 2>&1; then
    log "  远端已有：$img"
  else
    log "  push  $img"
    docker push "$img" || die "docker push 失败：$img（是否已 docker login harbor.xnunion.com？）"
  fi
}

BACKENDS=(order system gateway knowledge ai push)

# ---------- 参数解析 ----------
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then usage; exit 0; fi

SERVICE="${1:-}"
TAG="${2:-}"
shift 2 2>/dev/null || true
for arg in "$@"; do
  case "$arg" in
    --force)    FORCE=1 ;;
    --yes)      ASSUME_YES=1 ;;
    --no-image) SKIP_IMAGE=1 ;;
    --allow-downgrade) ALLOW_DOWNGRADE=1 ;;
    *) die "未知参数：$arg（用 --help 查看用法）" ;;
  esac
done

if [ -z "$SERVICE" ] || [ -z "$TAG" ]; then
  usage
  echo
  die "缺少参数：需要 <service> <tag>"
fi

case "$SERVICE" in
  front|ai|gateway|knowledge|order|push|system|all) ;;
  *) die "不支持的 service：$SERVICE（可选 front/ai/gateway/knowledge/order/push/system/all）" ;;
esac

[[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || die "tag 含非法字符：$TAG"

command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"
[ -f "$OVERLAY_FILE" ] || die "找不到 overlay：$OVERLAY_FILE"
[ -d "$APPS_DIR" ] || die "找不到 apps 目录：$APPS_DIR"

# ---------- 环境自检 ----------
CTX="$(kubectl config current-context 2>/dev/null || true)"
[ -n "$CTX" ] || die "无法读取当前 kube-context（kubeconfig 未配置？）"

log "kube-context : $CTX"
log "namespace    : $NAMESPACE"
log "repo root    : $REPO_ROOT"

POD_COUNT="$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if ! kubectl -n "$NAMESPACE" get pods >/dev/null 2>&1; then
  warn "命名空间 $NAMESPACE 不存在或无权限访问"
else
  log "现有 Pod 数  : $POD_COUNT"
  kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null | awk '{print "    "$1"  "$2"  "$3}' | head -20 || true
fi

if [ -n "${EXPECTED_CONTEXT:-}" ] && [ "$CTX" != "$EXPECTED_CONTEXT" ] && [ "$FORCE" -ne 1 ]; then
  die "当前 context ($CTX) 与 EXPECTED_CONTEXT ($EXPECTED_CONTEXT) 不一致。确认无误请追加 --force"
fi

# ---------- git 工作区检查 ----------
if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  DIRTY="$(git -C "$REPO_ROOT" status --porcelain -- deploy/ 2>/dev/null || true)"
  if [ -n "$DIRTY" ]; then
    warn "deploy/ 下有未提交改动："
    printf '%s\n' "$DIRTY" | sed 's/^/    /'
    if [ "$ASSUME_YES" -ne 1 ] && [ -t 0 ]; then
      read -r -p "继续执行？(y/N) " ans
      [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "已取消"
    else
      warn "非交互模式，继续执行（如需中止请 Ctrl-C）"
    fi
  fi
fi

# ---------- 读写 overlay 的 newTag ----------
# 打印当前某个服务的 tag
current_tag() {
  local image="$1"
  awk -v target="$image" '
    /^[[:space:]]*newName:/ {
      line=$0; sub(/^[[:space:]]*newName:[[:space:]]*/, "", line); gsub(/[\"[:space:]]/, "", line);
      hit = (line == target)
    }
    /^[[:space:]]*newTag:/ && hit {
      v=$0; sub(/^[[:space:]]*newTag:[[:space:]]*/, "", v); gsub(/[\"[:space:]]/, "", v);
      print v; exit
    }
  ' "$OVERLAY_FILE"
}

# 把某个服务的 newTag 改成 $2
set_tag() {
  local image="$1" tag="$2" file="$OVERLAY_FILE"
  awk -v target="$image" -v tag="$tag" '
    /^[[:space:]]*newName:/ {
      line=$0; sub(/^[[:space:]]*newName:[[:space:]]*/, "", line); gsub(/[\"[:space:]]/, "", line);
      hit = (line == target)
    }
    /^[[:space:]]*newTag:/ && hit {
      match($0, /^[[:space:]]*/);
      printf "%snewTag: \"%s\"\n", substr($0, 1, RLENGTH), tag;
      hit=0; next
    }
    { print }
  ' "$file" > "$file.tmp"
  mv "$file.tmp" "$file"
}

backup() {
  local f="$1"
  [ -f "$f.bak" ] || cp -p "$f" "$f.bak"
  BAK_FILES+=("$f")
}

restore_all() {
  local f
  for f in "${BAK_FILES[@]:-}"; do
    [ -n "$f" ] && [ -f "$f.bak" ] && cp -p "$f.bak" "$f" && rm -f "$f.bak"
  done
}

apply_overlay() {
  kubectl apply -k "$OVERLAY_DIR"
}

# ---------- 部署前预检 ----------
# 渲染一次 overlay，打印全部 Deployment 的 image 行与关键配置项，并与集群现状对比。
# 发现版本回退（数字 tag 变小）时默认终止，必须交互输入 DOWNGRADE 或显式 --allow-downgrade。
image_tag() { printf '%s' "${1##*:}"; }

is_version_regression() {
  local old="$1" new="$2"
  [[ "$old" =~ ^[0-9]+([.][0-9]+)*$ ]] || return 1
  [[ "$new" =~ ^[0-9]+([.][0-9]+)*$ ]] || return 1
  [ "$old" != "$new" ] || return 1
  awk -v a="$old" -v b="$new" 'BEGIN{
    na=split(a,x,"."); nb=split(b,y,"."); n=(na>nb?na:nb);
    for(i=1;i<=n;i++){
      xi=(i<=na?x[i]:0)+0; yi=(i<=nb?y[i]:0)+0;
      if(xi!=yi){ exit (yi<xi)?0:1 }
    }
    exit 1
  }'
}

cluster_cm_value() {
  kubectl -n "$NAMESPACE" get configmap "$1" -o jsonpath="{.data.$2}" 2>/dev/null || true
}

# 隐性故障检查：抽取/复杂路由模型未配置时会回落 glm-5.3-flash，
# Pod 能正常启动，但公司 vLLM 没有该模型，ticket.closed 抽取必定 404。
# 只比 value 差异发现不了「两边都缺失」，所以单独查渲染值与集群值。
check_ai_default_model() {
  local key="$1" rendered="$2" cm="$3" cluster issue=""
  cluster="$(cluster_cm_value "$cm" "$key")"
  if [ -z "$rendered" ]; then
    issue="$key 未出现在渲染结果（应用回落默认 glm-5.3-flash）"
  elif [ "$rendered" = "glm-5.3-flash" ]; then
    issue="$key 渲染值=glm-5.3-flash"
  fi
  if [ -z "$cluster" ]; then
    issue="${issue}${issue:+；}集群（apply 前）$cm/$key 为空或取不到"
  elif [ "$cluster" = "glm-5.3-flash" ]; then
    issue="${issue}${issue:+；}集群（apply 前）$cm/$key=glm-5.3-flash"
  fi
  [ -n "$issue" ] && printf '%s\n' "$issue"
  return 0
}

# 链式抽取开关：默认 false 时 rootCause/verification/hasFinalRootCause/chainTrace
# 全为 null，审核页显示「（无最终根因）」。空值/非 true 一律告警。
check_chain_enabled() {
  local rendered="$1" cluster issue=""
  cluster="$(cluster_cm_value "ticket-ai-config" "TIMS_AI_EXTRACT_CHAIN_ENABLED")"
  if [ -z "$rendered" ]; then
    issue="渲染结果缺少 TIMS_AI_EXTRACT_CHAIN_ENABLED（应用默认 false）"
  elif [ "$rendered" != "true" ]; then
    issue="渲染值=$rendered（期望 true）"
  fi
  if [ -z "$cluster" ]; then
    issue="${issue}${issue:+；}集群（apply 前）ticket-ai-config/TIMS_AI_EXTRACT_CHAIN_ENABLED 为空或取不到"
  elif [ "$cluster" != "true" ]; then
    issue="${issue}${issue:+；}集群（apply 前）ticket-ai-config/TIMS_AI_EXTRACT_CHAIN_ENABLED=$cluster"
  fi
  [ -n "$issue" ] && printf '%s\n' "$issue"
  return 0
}

# 交互确认；返回非 0 表示未确认
confirm_downgrade() {
  local ans
  if [ "$ALLOW_DOWNGRADE" -eq 1 ]; then
    warn "已指定 --allow-downgrade，跳过版本回退的交互确认"
    return 0
  fi
  if [ -t 0 ]; then
    printf '确认按上述渲染结果降级，请输入 DOWNGRADE（其它任意输入取消）: '
    read -r ans
    if [ "$ans" = "DOWNGRADE" ]; then return 0; fi
    return 1
  fi
  return 1
}

preflight() {
  local dep img cur old new cm key val cmval
  local CLUSTER_IMAGES=""
  local regressions=()
  local drifts=()
  local missing=()
  local dup_lines=""
  local render_extract=""
  local render_complex=""
  local render_chain=""
  local ai_model_issues=""
  local chain_issues=""
  local addr_hits=""

  # 静态检查：base/ 不允许残留公司内网地址（应在 overlays/company/patches/ 覆盖）。
  # 覆盖 172.27.x、10.96.x，以及 CGNAT 段 100.64.0.0/10（100.64～100.127，
  # 公司 pod 网段落在这里，Endpoints 常见 100.7x/100.9x/100.12x）。
  addr_hits="$(grep -RInE --exclude='*.bak' \
    '172\.27\.|10\.96\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.' \
    "$BASE_DIR" 2>/dev/null || true)"
  if [ -n "$addr_hits" ]; then
    printf '\n################################################################\n'
    printf '[WARN] base/ 中发现公司内网地址（应下沉到 overlays/company/patches/）：\n'
    printf '%s\n' "$addr_hits" | sed 's/^/  /'
    printf '################################################################\n'
  fi

  log "部署前预检：渲染 overlay"
  RENDER_TMP="$(mktemp)"
  if ! kubectl kustomize "$OVERLAY_DIR" > "$RENDER_TMP" 2>"$RENDER_TMP.err"; then
    [ -s "$RENDER_TMP.err" ] && sed 's/^/    /' "$RENDER_TMP.err" >&2
    rm -f "$RENDER_TMP" "$RENDER_TMP.err"; RENDER_TMP=""
    restore_all
    die "kustomize 渲染失败，已还原清单，未改动集群"
  fi
  rm -f "$RENDER_TMP.err"

  CLUSTER_IMAGES="$(
    kubectl -n "$NAMESPACE" get deploy \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}' 2>/dev/null || true
    kubectl -n "$NAMESPACE" get statefulset \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}' 2>/dev/null || true
  )"

  printf '\n================ 部署前预检：镜像 ================\n'
  while IFS=$'\t' read -r dep img; do
    [ -n "$dep" ] || continue
    cur="$(printf '%s\n' "$CLUSTER_IMAGES" | awk -F'\t' -v d="$dep" '$1==d{print $2; exit}')"
    printf '  %-22s %s\n' "$dep" "$img"
    if [ -z "$cur" ]; then
      printf '  %-22s   -> 集群现状：未取到（不存在或无权限）\n' ""
      missing+=("$dep")
    elif [ "$cur" != "$img" ]; then
      printf '  %-22s   -> 集群现状：%s\n' "" "$cur"
      old="$(image_tag "$cur")"; new="$(image_tag "$img")"
      if is_version_regression "$old" "$new"; then
        regressions+=("$dep 集群=$old 渲染=$new")
      fi
    else
      printf '  %-22s   -> 集群现状：一致\n' ""
    fi
  done < <(awk '
    /^kind: (Deployment|StatefulSet)[[:space:]]*$/ {kind=$2; name=""; img=""; next}
    /^kind: / {kind=$2; name=""; img=""; next}
    (kind=="Deployment" || kind=="StatefulSet") && name=="" && /^  name: / {name=$2; gsub(/"/,"",name); next}
    (kind=="Deployment" || kind=="StatefulSet") && img=="" && /^[[:space:]]+(- )?image: / {
      img=$0; sub(/^[[:space:]]*(- )?image:[[:space:]]*/,"",img); gsub(/"/,"",img);
      if (name!="") print name "\t" img
    }
    /^---[[:space:]]*$/ {kind=""; name=""; img=""}
  ' "$RENDER_TMP")

  printf '\n============ 部署前预检：关键配置项 ============\n'
  while IFS=$'\t' read -r cm key val; do
    [ -n "$cm" ] || continue
    case "$key" in
      LLM_EXTRACT_MODEL)       render_extract="$val" ;;
      AI_ROUTER_COMPLEX_MODEL) render_complex="$val" ;;
      TIMS_AI_EXTRACT_CHAIN_ENABLED) render_chain="$val" ;;
    esac
    cmval="$(cluster_cm_value "$cm" "$key")"
    if [ -z "$cmval" ]; then
      printf '  %-24s %-34s = %s\n' "$cm" "$key" "$val"
      printf '  %-24s   -> 集群现状：该 key 不存在\n' ""
      drifts+=("$cm/$key 集群=(缺失) 渲染=$val")
    elif [ "$cmval" != "$val" ]; then
      printf '  %-24s %-34s = %s\n' "$cm" "$key" "$val"
      printf '  %-24s   -> 集群现状：%s\n' "" "$cmval"
      drifts+=("$cm/$key 集群=$cmval 渲染=$val")
    else
      printf '  %-24s %-34s = %s  [与集群一致]\n' "$cm" "$key" "$val"
    fi
  done < <(awk '
    function flush(   i) {
      if (kind=="ConfigMap" && name!="") {
        for (i=1; i<=n; i++) print name "\t" keys[i] "\t" vals[i]
      }
      n=0; cur=0; kind=""; name=""
    }
    /^---[[:space:]]*$/ {flush(); next}
    /^kind: / {kind=$2; gsub(/"/,"",kind); next}
    /^  name: / && name=="" {name=$2; gsub(/"/,"",name); next}
    /^  (TIMS_KB_EMBEDDING_MODEL|TIMS_KB_EMBEDDING_DIMENSIONS|EMBED_USAGE_URL|ZHIPU_EMBEDDING_URL|LLM_BASE_URL|LLM_CHAT_MODEL|LLM_EXTRACT_MODEL|AI_ROUTER_COMPLEX_MODEL|SPRING_AI_OPENAI_CHAT_OPTIONS_MODEL|TIMS_AI_EXTRACT_CHAIN_ENABLED|NACOS_ADDR|KB_GATE_ENABLED|KB_GATE_THRESHOLD|KB_GATE_SOFT_BAND|KB_EMBED_QUERY_INSTRUCTION):/ {
      line=$0; sub(/^  /,"",line);
      key=line; sub(/:.*/,"",key);
      val=line; sub(/^[^:]*:[[:space:]]*/,"",val); gsub(/^"|"$/,"",val);
      keys[++n]=key; vals[n]=val; cur=n; next
    }
    cur>0 && /^    [^ ]/ {
      cont=$0; sub(/^    /,"",cont); vals[cur]=vals[cur] " " cont; next
    }
    { if ($0 !~ /^    /) cur=0 }
    END {flush()}
  ' "$RENDER_TMP")

  ai_model_issues="$(
    check_ai_default_model "LLM_EXTRACT_MODEL" "$render_extract" "ticket-ai-config"
    check_ai_default_model "AI_ROUTER_COMPLEX_MODEL" "$render_complex" "ticket-ai-config"
  )"
  if [ -n "$ai_model_issues" ]; then
    printf '\n################################################################\n'
    printf '[WARN] 隐性故障：抽取/复杂路由模型仍是默认值（能启动，但一定调不通）\n'
    printf '%s\n' "$ai_model_issues" | sed 's/^/  - /'
    printf '  预期：LLM_EXTRACT_MODEL / AI_ROUTER_COMPLEX_MODEL = Qwen/Qwen3.8-27B-dev\n'
    printf '  后果：ticket.closed 抽取在 ticket-ai 调 vLLM 时 404，工单落 MANUAL_REQUIRED\n'
    printf '  注意：ConfigMap 变更不会重启 Pod；apply 后必须 rollout restart deploy/ticket-ai\n'
    printf '################################################################\n'
  fi

  chain_issues="$(
    check_chain_enabled "$render_chain"
  )"
  if [ -n "$chain_issues" ]; then
    printf '\n################################################################\n'
    printf '[WARN] 链式抽取未开启：tims.ai.extract.chain-enabled 为空或非 true\n'
    printf '%s\n' "$chain_issues" | sed 's/^/  - /'
    printf '  后果：rootCause / verification / hasFinalRootCause / chainTrace 全为 null，\n'
    printf '        审核页显示「（无最终根因）」，入库也会带空根因\n'
    printf '  注意：ConfigMap 变更不会重启 Pod；apply 后必须 rollout restart deploy/ticket-ai\n'
    printf '################################################################\n'
  fi

  if [ ${#drifts[@]} -gt 0 ]; then
    printf '\n[WARN] 发现 %d 处配置漂移（apply 会用渲染值覆盖集群现状）：\n' "${#drifts[@]}"
    printf '       %s\n' "${drifts[@]}"
  fi

  # 同一 Pod 内跨 ConfigMap 重复 key：只告警，不阻断。
  # 判据收窄为“同一个 Deployment/StatefulSet 的 envFrom 里同时引用的多个 ConfigMap
  # 存在同名 key”。各服务各自的 ConfigMap（如各自的 SERVER_PORT）不属于冲突。
  # 同一 key 被同一 Pod 的多个 envFrom 同时引用时，后加载者生效，改一处不生效。
  dup_lines="$(awk '
    function finish(   i) {
      if (kind=="ConfigMap" && cmname!="") {
        for (i=1; i<=nkeys; i++) cmkey[cmname SUBSEP keyarr[i]]=1
      }
      if ((kind=="Deployment" || kind=="StatefulSet") && wlname!="" && ncm>1) {
        nwl++; wl[nwl]=wlname; wln[nwl]=ncm
        for (i=1; i<=ncm; i++) wlc[nwl SUBSEP i]=cms[i]
      }
      kind=""; cmname=""; nkeys=0; in_data=0; wlname=""; ncm=0; in_env=0; pending=0
    }
    /^---[[:space:]]*$/ { finish(); next }
    /^kind: / { kind=$2; gsub(/"/,"",kind); next }
    /^  name: / {
      nm=$2; gsub(/"/,"",nm)
      if (kind=="ConfigMap") cmname=nm
      else if (kind=="Deployment" || kind=="StatefulSet") wlname=nm
      next
    }
    kind=="ConfigMap" && /^data:[[:space:]]*$/ { in_data=1; next }
    kind=="ConfigMap" && in_data && /^  [A-Za-z_][A-Za-z0-9_.-]*:/ {
      line=$0; sub(/^  /,"",line); sub(/:.*/,"",line); keyarr[++nkeys]=line; next
    }
    kind=="ConfigMap" && in_data && /^[^[:space:]]/ { in_data=0 }
    (kind=="Deployment" || kind=="StatefulSet") && /^[[:space:]]*envFrom:[[:space:]]*$/ {
      match($0,/^ */); env_ind=RLENGTH; in_env=1; pending=0; next
    }
    (kind=="Deployment" || kind=="StatefulSet") && in_env {
      if ($0 ~ /^[[:space:]]*$/) next
      match($0,/^ */); ind=RLENGTH
      if (ind<=env_ind && $0 !~ /^[[:space:]]*-/) { in_env=0; next }
      if ($0 ~ /^[[:space:]]*-[[:space:]]*configMapRef:[[:space:]]*$/) { pending=1; next }
      if (pending && $0 ~ /^[[:space:]]*name:[[:space:]]*/) {
        v=$0; sub(/^[[:space:]]*name:[[:space:]]*/,"",v); gsub(/"/,"",v)
        cms[++ncm]=v; pending=0; next
      }
      if ($0 ~ /^[[:space:]]*-[[:space:]]*/) { pending=0; next }
      next
    }
    END {
      finish()
      for (i=1; i<=nwl; i++) {
        for (k in cnt) delete cnt[k]
        for (k in src) delete src[k]
        for (j=1; j<=wln[i]; j++) {
          cm=wlc[i SUBSEP j]
          for (p in cmkey) {
            split(p, a, SUBSEP)
            if (a[1]==cm) {
              k=a[2]; cnt[k]++
              src[k]=src[k] (src[k]=="" ? "" : ", ") cm
            }
          }
        }
        for (k in cnt) if (cnt[k]>1) print wl[i] "\t" k "\t" src[k]
      }
    }
  ' "$RENDER_TMP" | sort)"
  if [ -n "$dup_lines" ]; then
    printf '\n################################################################\n'
    printf '[WARN] 同一 Pod 同时 envFrom 的多个 ConfigMap 存在同名 key（后加载者生效，改一处不生效）\n'
    while IFS=$'\t' read -r wl key srcs; do
      [ -n "$wl" ] || continue
      printf '  - %-20s %-34s 同时引用: %s\n' "$wl" "$key" "$srcs"
    done <<< "$dup_lines"
    printf '################################################################\n'
  fi

  if [ ${#missing[@]} -gt 0 ] && [ -z "$CLUSTER_IMAGES" ]; then
    warn "无法读取集群 Deployment 列表（命名空间/权限/context），本次只打印渲染结果，未做对比"
  fi

  if [ ${#regressions[@]} -gt 0 ]; then
    cat <<EOF

################################################################
[WARN] 检测到版本回退：apply -k 会把以下服务降级
$(printf '  - %s\n' "${regressions[@]}")

继续后 Deployment 会按渲染 tag 重建；Harbor 上没有该 tag 时 Pod 会 ImagePullBackOff。
本次 apply 前的集群版本（即回滚目标）：
$(printf '%s\n' "$CLUSTER_IMAGES" | awk -F'\t' 'NF>=2 {printf "  %-22s %s\n", $1, $2}')

回滚方式（任选其一）：
  1) ./deploy.sh <service> <上面的旧tag> --no-image --yes --allow-downgrade
  2) kubectl -n $NAMESPACE rollout undo deploy/<deployment>
  3) 仅回滚配置：改回 $OVERLAY_DIR/patches/ 后
     kubectl apply -k $OVERLAY_DIR && kubectl -n $NAMESPACE rollout restart deploy/<deployment>
################################################################
EOF
    if ! confirm_downgrade; then
      restore_all
      die "版本回退未确认，已还原清单，未改动集群"
    fi
  else
    log "预检通过：渲染结果无版本回退"
  fi
}

# ---------- 单个后端：改清单 ----------
prepare_backend() {
  local svc="$1" tag="$2" manifest image src_image
  manifest="$(svc_manifest "$svc")"
  image="$(svc_image "$svc")"
  src_image="$(svc_src_image "$svc")"

  [ -f "$manifest" ] || die "找不到清单：$manifest"

  ORIG_TAG="$(current_tag "$image")"
  [ -n "$ORIG_TAG" ] || die "overlay 里找不到 $image 的 newTag，无法确定回滚目标"

  backup "$OVERLAY_FILE"
  backup "$manifest"

  set_tag "$image" "$tag"
  # 同步 base 清单 image 行（不生效，只为仓库可读与后续对照）
  sed -i "s|image:[[:space:]]*${src_image}:[^[:space:]]*|image: ${src_image}:${tag}|" "$manifest"

  log "  $svc: $ORIG_TAG -> $tag  ($(basename "$manifest"))"
}

# 从清单里取某个镜像的当前 tag
manifest_image_tag() {
  local file="$1" target="$2"
  awk -v target="$target" '
    /^[[:space:]]*(- )?image:[[:space:]]*/ {
      line=$0; sub(/^[[:space:]]*(- )?image:[[:space:]]*/,"",line); gsub(/"/,"",line);
      if (index(line, target ":")==1) { print substr(line, length(target)+2); exit }
    }
  ' "$file"
}

rollout_one() {
  local dep="$1"
  log "rollout status deploy/$dep ..."
  if ! kubectl -n "$NAMESPACE" rollout status "deploy/$dep" --timeout=180s; then
    return 1
  fi
  local image pod
  image="$(kubectl -n "$NAMESPACE" get deploy "$dep" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  pod="$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null | awk -v p="$dep-" 'index($1,p)==1 {print $1}' | tail -1)"
  log "  ✔ $dep"
  log "    image: $image"
  log "    pod  : ${pod:-（未取到）}"
}

print_debug_hints() {
  local dep="$1"
  cat <<EOF

排错命令：
  kubectl -n $NAMESPACE describe deploy/$dep
  kubectl -n $NAMESPACE get pods | grep $dep
  kubectl -n $NAMESPACE logs deploy/$dep --tail=50
  kubectl -n $NAMESPACE describe pod \$(kubectl -n $NAMESPACE get pods --no-headers | awk -v p="$dep-" 'index(\$1,p)==1 {print \$1}' | tail -1)
EOF
}

# ---------- 主流程 ----------
TARGETS=()
if [ "$SERVICE" = "all" ]; then
  TARGETS=("${BACKENDS[@]}")
else
  TARGETS=("$SERVICE")
fi

log "目标服务：${TARGETS[*]}   目标 tag：$TAG"

# 3) 镜像准备：本机没有就 load，Harbor 上没有就 push
if [ "$SKIP_IMAGE" -eq 0 ]; then
  log "镜像准备（IMAGES_DIR=$IMAGES_DIR）"
  for svc in "${TARGETS[@]}"; do
    ensure_image "$svc" "$TAG"
  done
else
  log "跳过镜像准备（--no-image）"
fi

# 4) 改清单：前后端统一改 overlay 的 newTag，并同步 base 的 image 行
PREPARE_FAILED=0
for svc in "${TARGETS[@]}"; do
  if ! prepare_backend "$svc" "$TAG"; then PREPARE_FAILED=1; break; fi
done

if [ "$PREPARE_FAILED" -ne 0 ]; then
  restore_all
  die "准备阶段失败，已还原文件，未改动集群"
fi

# 4b) 部署前预检：必须在任何集群写操作之前
preflight

# 4c) apply（后端与前端统一走 apply -k）
log "kubectl apply -k $OVERLAY_DIR"
if ! apply_overlay; then
  restore_all
  die "apply 失败，已还原清单"
fi

# 5/6) rollout
ROLLOUT_FAILED=0
for svc in "${TARGETS[@]}"; do
  if ! rollout_one "$(svc_deploy "$svc")"; then
    ROLLOUT_FAILED=1
    FAILED_SVC="$svc"
    break
  fi
done

# 7) 失败回滚
if [ "$ROLLOUT_FAILED" -ne 0 ]; then
  warn "服务 $FAILED_SVC 发布失败，开始回滚"
  restore_all
  apply_overlay || warn "回滚 apply 也失败了，请手动修复"

  if [ "$SERVICE" = "all" ]; then
    warn "已整体回滚（${SERVICE}）"
  else
    warn "已回滚到原 tag：$(current_tag "$(svc_image "$FAILED_SVC")" 2>/dev/null || echo '见 .bak')"
  fi
  print_debug_hints "$(svc_deploy "$FAILED_SVC")"
  exit 1
fi

# 清理 .bak
for f in "${BAK_FILES[@]:-}"; do [ -n "$f" ] && rm -f "$f.bak"; done

log "部署完成：${TARGETS[*]} -> $TAG"
for svc in "${TARGETS[@]}"; do
  dep="$(svc_deploy "$svc")"
  img="$(kubectl -n "$NAMESPACE" get deploy "$dep" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo '?')"
  printf '  %-10s %-18s %s\n' "$svc" "$dep" "$img"
done
