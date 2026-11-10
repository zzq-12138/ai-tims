# 六服务统一运行镜像（构建期在 VM 上执行，产物再离线搬运）。
# 构建上下文必须是仓库根目录，JAR_FILE 由 build-images.sh 以相对路径传入。
FROM eclipse-temurin:17-jre-jammy

ARG JAR_FILE

ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8

RUN groupadd -g 10001 tims \
    && useradd -u 10001 -g tims -m -s /bin/bash tims

WORKDIR /app
COPY ${JAR_FILE} /app/app.jar

# logback 写 ./logs/ai-tims.log：目录必须存在且归 10001，否则非 root 启动即失败
RUN mkdir -p /app/logs \
    && chown -R 10001:10001 /app

USER 10001:10001

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
