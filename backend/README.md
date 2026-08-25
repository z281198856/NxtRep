# NxtRep Backend

FastAPI + LangChain 后端骨架。当前目标是先固定模块边界和最重要的安全约束，尚未实现完整业务。

## 本地启动

需要 Python 3.12+。推荐使用 `uv`：

```bash
uv sync --extra dev
copy .env.example .env
uv run uvicorn nxtrep_backend.main:app --reload --app-dir src
```

访问：

- `GET /health`
- `GET /api/v1/health`
- `POST /api/v1/agent/chat`
- `POST /api/v1/confirmations`
- `GET /docs`

受保护接口使用 `Authorization: Bearer <access_token>`。服务端会验证 JWT 签名和有效期，并确认对应用户仍然存在、已启用且完成了首次密码设置。

## 本地创建账号

项目不开放注册。使用本地命令创建账号，并通过隐藏输入设置初始密码：

```bash
uv run python -m nxtrep_backend.cli.create_user --username Qiiii --set-password
```

昵称可稍后通过个人档案接口设置；如需在创建时填写，增加 `--display-name "昵称"`。

## 设计约束

- Agent 工具按请求绑定用户，避免跨用户读取。
- Agent 运行时只注册只读工具；变更通过 confirmation draft 独立建模。
- 训练计划采用版本、训练记录采用快照；后续修改不能改写历史。
- 营养数据、体脂估算保留来源、置信度和范围，不伪装成精确测量。
- 所有写入应使用幂等键和审计记录，以支持 iOS 端离线重试。

## 建议实现顺序

1. 账号、档案、训练计划版本和训练快照。
2. 训练组记录的幂等写入与同步冲突处理。
3. 饮食、身体数据、趋势和周报。
4. Agent 会话、确认执行、Memory 和主动消息。
