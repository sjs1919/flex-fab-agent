# 部署规范

> 本文件定义部署通用原则。技术栈相关的构建/环境/重启细节见对应 `stack-*/build.md`、`stack-*/ops.md`。
> 服务器操作边界见 `common/server-approval.md`。

## 部署金线

1. **先写文档再部署（🚫 无文档禁止部署）** — 每次部署前必须先产出部署文档（写入 `10-deployment/`），结构见下方「部署文档」节。文档未写或结构不完整，禁止进入下一步。
2. **先审核后执行** — 部署文档提交用户审核，审核通过并签字后方可执行部署操作。AI 不得在文档未获批的情况下自主触发任何部署动作。
3. **先备后替** — 部署前备份当前镜像/配置/数据库，确保可回滚
4. **先停后启** — 优雅停止旧进程（给 in-flight 请求完成时间），确认端口释放，再启动新进程
5. **先验后收** — 部署后必须跑完整链路验证清单，全部 PASS 才称部署完成

## 部署文档

每次部署必须产出一份部署清单文档（写入文档仓 `10-deployment/`），包含以下固定结构：

| 节 | 内容 |
|----|------|
| 变更范围 | 涉及提交/文件/变更量（含"不动"声明——哪些组件本次不碰） |
| 部署前架构 | 当前哪些服务运行在哪些端口，使用哪些镜像 |
| 构建 | 编译命令 + 镜像构建 Dockerfile + 镜像标签 |
| 备份 | 旧镜像导出、当前配置备份，确认路径和文件大小 |
| 替换 | Graceful stop→rm→load new→run 完整命令序列 |
| 验证 | 逐端口/逐端点/逐路径 curl 全量检查（见下方验证清单模板） |
| 回滚 | 完整的恢复命令序列（旧镜像+旧配置），可直接复制执行 |
| 踩坑 | 本次部署中遇到的所有问题 + 根因 + 修复方案 + 预防措施 |

## 部署验证清单（每次部署后强制执行）

```
□ 容器状态：docker ps 全部服务 Up/healthy
□ 存活探针：curl /health → 200 + alive
□ 就绪探针：curl /ready → 200 + ready（含 DB 连通）
□ 前端入口：curl /  + 关键 SPA 路由 → 200（非 301/302）
□ API 代理：/api/ 路径经 Nginx 正确代理到后端
□ 公网可达：从前端域名或公网 IP curl 全部关键端点
□ 日志无异常：docker logs --tail=10 | grep -iE "panic|fatal|error" → 空
```

## 健康检查双探针（强制）

| 端点 | 用途 | 检查内容 | 响应 |
|------|------|---------|------|
| `/health` | 存活检查（liveness） | 进程是否活着 | 200 + `{"status":"alive"}` |
| `/ready` | 就绪检查（readiness） | DB/上游依赖是否可达 | 200 + `{"status":"ready"}` 或 503 |

- Docker 容器必须配置 HEALTHCHECK（interval 30s, timeout 10s, retries 3）
- 部署验证必须两个端点都 curl 并确认状态字段
- 负载均衡/K8s 以此区分「进程活着但 DB 不可用」与「进程挂了」

## Nginx 反向代理（单机部署标准拓扑）

```
:80  → Nginx（static files + 反向代理）
       ├── /            → 前端 SPA 静态文件（try_files $uri $uri/ /index.html）
       ├── /api/        → 后端 HTTP（read_timeout 60s）
       ├── /v1/         → SSE 流式（read_timeout 300s, buffering off, http 1.1）
       └── /health, /ready → 后端（access_log off）
```

- 后端端口不对外暴露，仅 127.0.0.1
- SPA 路由 `try_files $uri $uri/ /index.html` 不可省略（history 模式）
- `~ /\.` 拒绝隐藏文件访问
- 静态资源长缓存（Vite/Webpack hash 文件名可永久缓存）

## Docker 多阶段构建

```
阶段1 前端构建 → 阶段2 后端构建 + 复制 dist → 阶段3 运行时（仅二进制 + dist + ca-certificates）
```

- 不使用多阶段构建时，构建上下文体积不宜过大（历史：719MB 卡死）
- 最终镜像仅保留二进制 + dist + ca-certificates + tzdata，非 root 运行
- `docker save` 导出镜像时用 `.tar` 格式，`docker load -i` 导入

## 防火墙

| 端口 | 协议 | 来源 |
|------|------|------|
| 22 | TCP | 允许 |
| 80/443 | TCP | 允许 |
| 后端端口 | TCP | 仅 127.0.0.1 |
| DB 端口 | TCP | 仅 127.0.0.1 或内网 |

## 回滚

- 回滚命令必须事先写在部署文档中，可直接复制执行，临时拼凑禁止部署
- 回滚后必须重跑完整验证清单确认恢复
- 旧镜像保留到部署验证通过后再 `docker image prune -f`

## 禁止事项

- 🚫 未跑完整验证清单声称部署完成
- 🚫 无备份直接覆盖（镜像/配置/DB）
- 🚫 容器重建后硬编码 IP 做 upstream（用 docker 网络别名或服务名）
- 🚫 部署后不检查日志异常（panic/fatal/error）
- 🚫 用 `docker compose restart`（发 SIGKILL，不优雅关闭）
- 🚫 AI 自主触发部署流程（门禁4 部署审批：先写文档 → 用户审核签字 → 执行）
