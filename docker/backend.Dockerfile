# AI-TIMS 后端通用镜像（参数化 Dockerfile，由 build-images.sh 按服务传入 jar）
# 基础镜像：eclipse-temurin:17-jre-alpine（精简 JRE，amd64）
FROM eclipse-temurin:17-jre-alpine

ARG JAR_FILE=target/app.jar
WORKDIR /app

COPY ${JAR_FILE} app.jar

ENV TZ=Asia/Shanghai \
    JAVA_OPTS=""

# 健康探针走各服务 /api/{svc}/ping（compose/k8s 层配置，镜像内不写死端口映射）
EXPOSE 8080

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
