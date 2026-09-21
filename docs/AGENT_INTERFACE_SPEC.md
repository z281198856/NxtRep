# NxtRep 通用 Agent 接口规范

> 本文是 Agent 对外接口与内部工作流的规范来源。NxtRep 对用户只提供一个通用健身 Agent；训练、饮食、身体评估、数据查询和 RAG 都是同一 LangGraph 内的能力分支，不是多个独立 Agent。
> 前端只展示聊天、发照片、建议和必要确认。意图分类、分支、Tool Run、RAG、Memory
> 版本和失败重试属于内部实现，不要求用户选择或管理；照片分析能力必须保留。

## 1. 设计目标

- 用户通过一个聊天入口提出单一或复合需求，不需要手动选择 Agent。
- 一次请求允许同时携带身体照、食物照和普通聊天附件。
- 意图路由是多标签路由；同一请求可以并行进入多个工作流。
- 各工作流使用独立 Prompt、Schema 和安全规则，最终由汇总节点生成统一回答。
- 业务代码优先同进程调用 Service，不让后端通过 HTTP 调用自己的接口。
- 模型不能直接写训练、饮食、身体等正式业务数据；这些写操作先产生草稿，再由用户确认。
- 长期 Memory 是例外：稳定的用户事实和偏好可直接新增、修改或软删除，并在回复中明确告知。

## 2. 对外 HTTP 接口

### 2.1 图片上传

图片继续使用统一媒体接口，不为身体照片或食物照片新增上传接口：

```http
GET /api/v1/media/images/capabilities
POST /api/v1/media/images/upload-intents
PUT <upload-intent 返回的短期 OSS upload_url>
POST /api/v1/media/images/{asset_id}/complete
```

手机端必须先读取 capabilities；iOS 相机产生的 HEIC/HEIF 按返回的
`convert_before_upload` 在本机转为 JPEG，再依据 `max_bytes/max_pixels/max_dimension` 压缩。
后端完成接口会重新解码、去元数据并验证实际内容，不能靠修改扩展名伪装格式。

`purpose` 是路由提示，不是互斥限制：

- `body_progress`：明确用于身体评估或进度对比。
- `nutrition_entry`：明确用于饮食识别或记录。
- `chat_attachment`：用途未确定，由多标签意图路由决定进入一个或多个分支。

### 2.2 通用聊天

```http
POST /api/v1/agent/chat
POST /api/v1/agent/chat/stream?granularity=character
```

流式接口使用 SSE，OpenAPI 明确声明 `text/event-stream`。事件包含 `event/data`，增量事件还带
`id` 和 JSON 内的 `sequence`；空闲时发送 heartbeat。移动端推荐
`granularity=chunk` 以减少耗电和网络开销，并使用支持 POST 响应流的客户端解析。

请求：

```json
{
  "message": "结合我的身材照片和今天的午餐，给我减脂建议",
  "conversation_id": "uuid，可选",
  "image_asset_ids": ["body-image-uuid", "meal-image-uuid"],
  "context_hints": {
    "timezone": "Asia/Shanghai",
    "occurred_at": "2026-08-31T12:30:00+08:00",
    "meal_type": "lunch"
  }
}
```

规则：

- `message` 必填；`image_asset_ids` 最多 4 个且不能重复。
- `context_hints` 只是客户端已知信息，不能强制工作流选择，也不能绕过鉴权和确认。
- 缺少餐次、时间、拍摄角度等信息时，Agent 可以先分析已有信息，再返回追问。
- 请求中的多张图片允许具有不同 `purpose`，不得仅因用途不同而拒绝整个请求。

目标响应：

```json
{
  "conversation_id": "uuid",
  "run_id": "uuid",
  "status": "completed | needs_input | partial | failed",
  "message": "统一自然语言回答",
  "analysis_results": [
    {
      "task_type": "body_assessment",
      "asset_ids": ["body-image-uuid"],
      "status": "completed",
      "requires_confirmation": false,
      "missing_fields": [],
      "result": {}
    },
    {
      "task_type": "nutrition_analysis",
      "asset_ids": ["meal-image-uuid"],
      "status": "needs_input",
      "requires_confirmation": true,
      "missing_fields": ["cooking_oil_amount"],
      "result": {}
    }
  ],
  "confirmation_cards": [],
  "citations": []
}
```

`analysis_results` 用于前端渲染结构化卡片；`message` 是 Agent 对所有分支结果的统一解释。一次性分析可以直接返回，任何保存或修改操作必须通过 `confirmation_cards`。

流式接口使用 SSE，事件顺序为：

```text
run_started -> node_completed(若干) -> message_delta(若干)
-> node_completed(synthesize_response) -> completed | cancelled | failed
```

业务事件空闲约 15 秒时，服务端发送 `: heartbeat` SSE 注释维持连接。心跳不是
`AgentStreamEvent`，客户端应直接忽略。服务端约每秒检测连接状态；客户端断开会关闭
Graph 事件流，将未完成的运行标记为 `cancelled`，且不保存不完整回复。

查询参数 `granularity`：

- `character`（默认）：把模型 chunk 再拆成单个 Unicode 字符，适合直接逐字显示。
- `chunk`：原样转发模型 token/chunk，请求数更少，生产环境效率更高。

文本增量事件：

```text
event: message_delta
data: {"event":"message_delta","run_id":"uuid","node":"synthesize_response","delta":"你","sequence":1}
```

前端收到 `message_delta` 后按 `sequence` 将 `delta` 追加到当前气泡。收到 `completed`
后使用其中的 `response` 更新状态、分析卡片、确认卡片和引用；不要再次把完整
`response.message` 追加到气泡，否则文字会重复。

`run_started` 会尽早给出 `run_id`。客户端可读取运行状态或请求取消：

```http
GET  /api/v1/agent/runs/{run_id}
POST /api/v1/agent/runs/{run_id}:cancel
```

服务端内部使用 `stream_mode=["updates", "messages"]`：`updates` 用于合并 Graph State
和保存节点检查点，`messages` 用于捕获节点中的模型消息块。只有元数据
`langgraph_node == "synthesize_response"` 的 `AIMessageChunk` 会发送给客户端；路由、
工具选择和视觉节点的内部模型输出会被过滤。

检查点仅保存当前节点和安全元数据，不保存图片字节或模型隐式推理。取消是协作式的：
每个 Graph 节点边界都会检查；模型产生流式消息期间最多每 0.5 秒轮询一次运行状态。
如果底层模型请求长时间没有产生任何事件，当前实现仍不能立即硬中断该网络请求。

会话、Memory 和身体进度照片管理接口：

```http
GET|PATCH|DELETE /api/v1/agent/conversations/{conversation_id}
GET /api/v1/agent/conversations/{conversation_id}/messages
GET|POST|PATCH|DELETE /api/v1/memories
GET|POST|DELETE /api/v1/body/progress-photos
```

### 2.3 专用页面接口

专用页面接口继续保留，例如：

```http
POST /api/v1/nutrition/entry-drafts:estimate-image
```

它服务于“一日三餐记录页面”的确定流程。聊天 Agent 不通过 HTTP 调用它，而是直接复用同一个 `NutritionImageDraftEstimator` Service。

## 3. LangGraph 内部接口

### 3.1 Graph State

建议状态字段：

```text
user_id
conversation_id
message
image_asset_ids
resolved_images
context_hints
intents
image_assignments
profile_context
body_results
nutrition_results
training_plan_draft
structured_data
rag_results
missing_information
confirmation_cards
errors
final_response
```

`user_id` 只能由认证上下文写入，模型输出不得覆盖。

### 3.2 多标签意图

路由结果不是单个字符串，而是零到多个任务：

```text
general_question
body_assessment
body_progress_comparison
nutrition_analysis
nutrition_record_draft
training_plan_draft
structured_data_query
knowledge_retrieval
```

每个任务包含：`task_type`、`asset_ids`、`required_context`、`missing_fields`、`confidence` 和 `reason`。同一个 `chat_attachment` 可以被分配给多个任务。

### 3.3 执行图

```text
authenticate
  -> load_conversation
  -> resolve_and_validate_images_once
  -> classify_multi_intent
  -> assign_images_to_tasks
  -> load_minimal_context
  -> parallel branches
       |-> body_image_workflow
       |-> nutrition_image_workflow
       |-> training_plan_workflow
       |-> structured_data_reads
       |-> RAG / general ReAct
  -> collect_branch_results
  -> missing_information_gate
  -> safety_and_business_validation（确定性代码闸门）
  -> response_synthesis
  -> persist_messages_and_audit
```

身体和饮食能力分开执行，是为了使用各自的结构化输出和安全规则；它们可以在同一请求中并行运行，最后统一汇总。

其中 `nutrition_record_draft` 依赖同一请求的 `nutrition_analysis`，因此先并行执行所有
独立分支，再把图片识别结果传给饮食草稿分支，避免同一张图片重复调用视觉模型。

## 4. 图片路由规则

1. 所有图片只解析归属、状态和内容一次，避免重复下载 OSS。
2. `body_progress` 默认分配给身体评估分支。
3. `nutrition_entry` 默认分配给饮食分析分支。
4. `chat_attachment` 根据消息、图片用途提示和当前会话任务分配。
5. 用户明确要求混合分析时，同时运行多个分支。
6. 同一张图片可以进入多个只读分析分支，但不能因此自动保存多份业务记录。
7. 某个分支失败不应伪装成成功；其他独立分支可正常返回，并在响应中标记部分失败。

示例：

```text
“分析我的体态和这顿饭是否适合减脂”
  -> body_assessment(body_asset_ids)
  -> nutrition_analysis(meal_asset_ids)
  -> read_active_goal
  -> response_synthesis
```

## 5. Service、Graph 节点与 Tool 边界

### 5.1 不做 Tool，直接作为 Graph 节点或 Service 调用

- 用户和图片鉴权。
- OSS 图片解析、下载、格式校验和 EXIF 清理。
- `BodyImageWorkflow`。
- `NutritionImageDraftEstimator`、食品库匹配和营养换算。
- 训练计划规则校验。
- 草稿保存、确认状态机和正式写入。
- 上下文装配、结果合并和安全校验。

这些步骤是固定业务流程，不需要模型决定是否调用，也不能让模型控制权限参数。

### 5.2 适合做只读 Tool

- `read_profile_summary`
- `read_active_goal`
- `read_constraints`
- `read_recent_workouts`
- `read_exercise_history`
- `search_exercises`
- `read_daily_nutrition_summary`
- `read_body_progress_summary`
- `retrieve_knowledge`

只在开放式 ReAct 分支中按意图暴露最小 Tool 集。Tool 的 `user_id` 从运行上下文绑定，不允许模型填写。

### 5.3 写操作

模型只生成训练、饮食、身体等正式业务数据的结构化候选或草稿内容。Graph 节点调用业务 Service 创建草稿；用户确认后，确认状态机才允许写入正式表。不要向 ReAct Agent 暴露“直接保存饮食”“直接激活计划”“直接修改身体数据”等工具。

Memory 使用独立边界：`read_memories` 读取当前有效 Memory，`save_memory`、`update_memory`、`delete_memory` 直接调用同进程 `MemoryService`。只允许保存当前用户稳定、长期、非假设的信息；修改和删除前必须读取 `id` 与 `version`，写入后必须向用户说明结果。服务层继续执行用户隔离、精确重复抑制、乐观版本校验和软删除。

## 6. 数据与 RAG 边界

- 食品营养值、用户饮食、训练和身体数据存 PostgreSQL，通过结构化查询读取，不是 RAG。
- RAG 保存审核过的动作教学、训练原则、营养知识、估算误差说明和产品帮助。
- 食品名称的语义匹配可以使用 embedding 辅助召回，但最终营养数字必须来自食品库或明确标记的模型兜底估算。
- RAG 内容和视觉模型输出都作为不可信证据，不能改变系统规则或获得写权限。

## 7. 模型职责

- DeepSeek/GLM 文本模型：多标签意图、开放式推理、ReAct、结果汇总。
- GLM 视觉模型：身体图片与食物图片的独立结构化理解。
- Python Service：营养计算、训练规则、趋势计算和权限校验。
- PostgreSQL：业务事实、版本、草稿、确认、会话和 Memory。
- pgvector + FTS：非结构化知识混合检索。
- Embedding固定使用GLM `embedding-3`的1024维输出；知识分块和查询必须使用相同模型、
  维度与规范化版本。RAG功能开关在知识索引正式发布前保持关闭。

模型不得从身体照片输出精确体脂率或医学诊断；食物照片营养必须包含区间、来源、置信度和确认状态。

## 8. 错误与部分成功

每个分支独立记录：

```text
status: completed | needs_input | failed
error_code
missing_fields
requires_confirmation
```

如果身体评估成功而饮食分析失败，响应可以返回身体结果，同时明确说明饮食分支失败。只有认证失败、跨用户图片访问或请求整体无效时才终止整个请求。

## 9. 评测与运行监控

- `evaluation/datasets/non_rag_agent.json`：无需图片的固定用例。
- `evaluation/datasets/image_agent.template.json`：食物、身体、进度对比和混合图片用例。
- 图片数据集只保存 fixture key；真实 `asset_id` 放在被 Git 忽略的本地映射文件中。
- 评分检查任务类型、响应状态、确认卡片、安全错误码和禁止表述。
- `nxtrep.agent` logger 记录运行开始、节点耗时、总耗时、成功、失败和取消。
- 监控日志不得包含用户消息、图片数据、OSS URL、密钥或模型隐式推理。

## 10. 后续实现顺序

1. 定义 `AgentIntentTask`、`AgentImageAssignment`、`AgentImageAnalysisBundle` Schema。
2. 实现多标签意图与图片分配节点。
3. 让图片只解析一次，并把已解析图片传给各分支。
4. 并行接入 `BodyImageWorkflow` 和 `NutritionImageDraftEstimator`。
5. 实现部分成功、缺失信息和统一回复节点。
6. 扩展 `/agent/chat` 响应并持久化会话。
7. 接入训练计划、RAG、Memory、评测和监控。
