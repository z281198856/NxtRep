# NxtRep 后端实现状态

> 核对日期：2026-09-12
> 范围：仅后端与配套数据库、测试、运维文件；Flutter 前端暂不开发。

## 结论

规划内后端功能已经实现。FastAPI 当前生成 166 个 OpenAPI 路径、201 个操作和
222 个 Schema；保留的兼容别名因 `include_in_schema=False` 不计入该数字。
当前 Alembic 迁移头为 `e4b7c2a9d851`。

## 最新验证结果

- `RUN_DATABASE_TESTS=1` 的完整测试：873 passed、0 skipped、0 failed。
- Ruff 全量检查：通过。
- 最后一条迁移已完成 downgrade/upgrade 可逆性测试，随后 `alembic check` 未发现模型漂移。
- 开发计划已列出 OpenAPI 中全部 201 个公开操作，并逐项核对方法和路径，缺失 0 个。
- 唯一测试警告是当前 Windows 目录拒绝创建 `.pytest_cache`，不影响测试结果或业务代码。
- 本机未安装 Docker，因此镜像文件已完成但没有在本机执行实际 `docker build`。

## 已实现能力

- 账号、首次设密、登录、令牌刷新/撤销、个人档案、目标约束和通知设置。
- 动作库、自定义动作、内容反馈、动作媒体、替代动作和动作分类。
- 训练模板、计划草稿、校验、确认激活、版本、归档、日历改期/压缩/替换。
- 训练开始/暂停/继续/记录/修订/完成、有效时长、组间计时恢复、快照、PR、历史查询和渐进计划草稿。
- 食品与条码、食品版本、食谱、饮食草稿/记录/修订、目标、动态目标、周报与建议。
- 身体测量、体脂估算、趋势、肌群训练量、恢复、相关性、进度照片上传/分析/对比。
- Agent 会话、消息、运行状态、工具运行、分支编排、确认卡、Memory、安全与 SSE。
- RAG 来源登记、文件摄取、分块、Embedding、审核、发布、混合检索、引用和固定评测。
- 设备与推送令牌、通知、主动提醒、增量同步/冲突、导出、账户删除草稿和审计记录。
- 管理员用户、知识来源/文档/检索/重试接口，以及周/月/阶段报告。

用户界面统一遵循 [`SIMPLIFIED_PRODUCT_EXPERIENCE.md`](SIMPLIFIED_PRODUCT_EXPERIENCE.md)：
社交不进入产品；同步冲突、版本、审计和 Agent 内部编排默认隐藏；食物、身体和训练计划
照片分析继续保留。

## 关键安全和一致性规则

- 所有用户数据查询均以当前认证用户为边界；管理员接口额外检查 `is_admin`。
- 高影响修改通过 confirmation 两阶段执行，普通修改使用 `expected_version` 防止覆盖。
- 可重试创建接口使用 `Idempotency-Key`；历史训练和饮食保存快照或修订记录。
- 生产配置拒绝调试模式、短 JWT、默认数据库凭据和本地/通配 CORS 来源。
- 图片存储、视觉模型和文本模型未配置时返回可识别错误，不静默使用伪结果。
- 图片训练计划当前生成带 `IMAGE_PARSE_REQUIRES_REVIEW` 警告的候选草稿，提交前必须复核。
- 移动端契约明确 JWT 轮换和禁止缓存、HEIC/HEIF 转换与 OSS 直传、数据库隔离和 Agent SSE。

## 本地验证

在 `backend` 目录中运行：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m ruff check src migrations tests
.\.venv\Scripts\python.exe -m pytest -q
```

启动 API：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn nxtrep_backend.main:app --host 127.0.0.1 --port 8000
```

随后访问 `/api/v1/health/live`、`/api/v1/health/ready`、`/docs` 和 `/openapi.json`。

## 容器与生产前置条件

仓库包含 `backend/Dockerfile` 和 `backend/.dockerignore`。从仓库根目录构建：

```powershell
docker build -t nxtrep-backend .\backend
```

镜像以非 root 用户运行 API。部署平台还需要：

1. PostgreSQL 16+，并预先启用与配置维度匹配的 pgvector 扩展。
2. 先以有迁移权限的发布任务执行 `alembic upgrade head`，再启动 API 实例。
3. 设置 `NXTREP_ENVIRONMENT=production`、至少 32 字符的随机 JWT、非默认数据库账号和明确的 HTTPS CORS 来源。
4. 需要 Agent/RAG/图片功能时，再配置 DeepSeek 或 GLM、Embedding 和私有 OSS 凭据。
5. 对外部署时由反向代理或平台终止 TLS，并为 `/api/v1/agent/chat/stream` 禁用响应缓冲。

外部模型和 OSS 属于环境集成项；没有有效密钥时无法做线上调用，但普通账号、训练、饮食、
身体、同步和报告等数据库能力可独立运行。
