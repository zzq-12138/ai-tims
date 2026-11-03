# AI-TIMS 前端镜像：多阶段构建（node 编译 -> nginx 静态托管）
# 只在 VM 上构建；公司侧 load 到的是最终 nginx 镜像，无需 node
# -------------------- 阶段 1：编译 --------------------
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN npm run build

# -------------------- 阶段 2：托管 --------------------
FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
