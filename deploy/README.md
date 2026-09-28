# 后端上线准备（尚未部署）

这份清单供购买云服务器后执行。目前没有目标服务器或域名，不能把本机通过的测试视为线上验收；云 Mac 的 iOS 构建应排在稳定的 HTTPS API 上线之后。不要把本机 `backend/.env`、数据库快照、模型密钥或 OSS 密钥提交到 Git。

## 已具备

- `backend/Dockerfile` 可构建 API 镜像；生产配置会拒绝调试模式、短 JWT 密钥、默认数据库账号和宽泛或本地 CORS 来源。
- Alembic 迁移位于 `backend/migrations`；含知识库表的迁移要求目标数据库事先启用 `vector` 扩展。
- API 有 `/api/v1/health/live` 和检查数据库连接的 `/api/v1/health/ready`。
- 主动教练 worker 与 API 共用代码，但必须作为独立、单实例进程运行；不能把 worker 当作第二个 HTTP 服务。

## 获取服务器后

1. 确定服务器系统、CPU 架构、域名、HTTPS 证书、备份存放位置和密钥管理方式。仅向公网开放 HTTPS；PostgreSQL 和 API 内部端口不直接暴露到公网。
2. 准备 PostgreSQL 17 与兼容的 pgvector，创建数据库及最小权限应用账号。由数据库管理员执行 `CREATE EXTENSION IF NOT EXISTS vector;`，再核对扩展版本。当前本地验收版本是 pgvector 0.8.6。
3. 以 `backend/.env.production.example` 为键清单配置真实环境变量。数据库 URL、至少 32 字符的随机 JWT 密钥不可留空；如要开放 AI、图片上传和 RAG，再分别配置模型、OSS 与 RAG。不要使用本地开发的数据库密码。
4. 先在目标数据库执行 `alembic upgrade head`，确认迁移成功，再启动一个 API 实例并检查 `https://<API 域名>/api/v1/health/ready`。确认 TLS、登录、计划、食品、动作和训练写入的回归均通过，再扩大流量。
5. 只启动一个 `python -m nxtrep_backend.cli.run_proactive_worker --at 08:00` 进程，并由进程管理器负责重启。复用 API 镜像时须关闭该镜像的 HTTP 健康检查；不要同时部署另一套每日定时任务。
6. 上线前完成数据库自动备份、恢复演练、错误日志与磁盘容量告警。升级前先备份；在测试环境演练迁移和回滚。iOS 构建时再把 `API_BASE_URL` 指向已验证的 HTTPS 地址。

此处刻意不预设云厂商、反向代理或 Compose 文件。确定服务器与密钥方案后，再把具体部署文件和运维命令固定下来并在同架构环境验证。
