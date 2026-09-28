# 架构与关键取舍

NxtRep 是一个模块化单体：Flutter 客户端只通过 HTTP API 与后端通信，FastAPI 进程承载业务接口与 Agent 工作流；主动教练检查由同一代码库中的独立 worker 运行。这样可以复用业务规则，同时避免让定时任务依赖某个手机是否在线。

## 请求与数据流

1. Flutter 将访问令牌保留在内存，将刷新令牌放在系统安全存储；后端负责令牌轮换与撤销。
2. Router 处理认证、参数和响应，Pydantic Schema 约束输入；Service 执行业务规则，Repository 访问 PostgreSQL。Alembic 管理结构迁移。
3. 训练、饮食、身体数据都绑定当前用户。计划、饮食等历史记录保留版本或快照，避免后续内容修改悄悄改变既往记录。
4. 创建操作使用 `Idempotency-Key` 处理移动网络重试；修改使用 `expected_version` 防止静默覆盖。删除或 Agent 的高影响变更经确认流程执行。

源码入口：[`backend/src/nxtrep_backend/main.py`](../backend/src/nxtrep_backend/main.py)、[`backend/src/nxtrep_backend/api/routes/`](../backend/src/nxtrep_backend/api/routes/)、[`frontend/lib/features/`](../frontend/lib/features/)。

## AI 是建议层，不是隐式写入层

Agent 使用 LangGraph 路由训练、营养、身体评估与一般问答，并可读取经授权的业务数据。用户只面对一个教练入口。对话中的计划或正式记录修改先形成草稿/确认项，展示影响后再执行；长期记忆按单独的用户控制规则管理。后端返回的 SSE 事件由 Flutter 增量消费。

照片通过媒体接口先取得上传意图，再直传私有对象存储，随后交由对应业务流程解析。餐食图像只能估算食物和份量，客户端允许用户修改每项热量、蛋白质、碳水和脂肪后保存；没有识别结果时不自动生成正式饮食记录。体脂采用围度公式与范围展示，不把估算值写成设备实测。

RAG 使用 PostgreSQL 全文检索与 pgvector，知识来源先审核再发布。来源和许可范围见 [RAG 知识来源](RAG_KNOWLEDGE_SOURCES.md)。模型、Embedding 与对象存储均通过配置启用；无密钥时应显示可诊断的失败，而不是伪造回答。

## 主动服务与运行边界

主动教练 worker 与 API 共用 Service，但作为独立单实例进程运行。只有用户开启相关功能时才检查训练或饮食记录缺口；缺少记录只表示未知，不应推断用户没有训练或进食。未来部署需要数据库备份、worker 重启策略、通知投递监控和密钥管理。

当前只在本地 Android 模拟器验证移动端，正式后端尚未部署，iOS 构建/签名和真实餐食照片端到端验收仍在待办范围。本文描述已存在的代码结构，不把尚未上线的能力写成已交付服务。
