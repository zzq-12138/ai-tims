#!/bin/bash
# leave-gold-out 运行器：解压服务 jar 的依赖 -> 编译 LeaveGoldOut.java -> 执行
# 用法: bash leave_gold_out.sh <in.tsv> <out.tsv>
set -e
IN=$(realpath "$1")
OUT=$(realpath -m "$2")
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
JAR="$REPO_ROOT/ai-tims-parent/ticket-knowledge/target/ticket-knowledge-1.0.0-SNAPSHOT.jar"
LIBDIR="$REPO_ROOT/.m7lib"
CLASSDIR="$REPO_ROOT/.m7classes"

if [ ! -f "$JAR" ]; then
  echo "未找到 $JAR，请先构建 ticket-knowledge" >&2
  exit 1
fi
if [ ! -d "$LIBDIR/BOOT-INF/lib" ]; then
  mkdir -p "$LIBDIR"
  cd "$LIBDIR"
  jar xf "$JAR" BOOT-INF/lib
fi
mkdir -p "$CLASSDIR"
CP=$(ls "$LIBDIR"/BOOT-INF/lib/*.jar | tr '\n' ':')
javac -proc:none -cp "$CP" -d "$CLASSDIR" "$SCRIPT_DIR/LeaveGoldOut.java"
java -cp "$CP:$CLASSDIR" LeaveGoldOut run "$IN" "$OUT"
