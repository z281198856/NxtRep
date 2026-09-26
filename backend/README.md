# NxtRep Backend

FastAPI + LangChain/LangGraph 后端。账号、训练、饮食、身体数据、Agent、RAG、
同步、通知、导出、账户删除、审计和管理接口均已实现；前端不在本阶段范围内。
当前完成范围、验证结果和部署前置条件见
[`docs/BACKEND_IMPLEMENTATION_STATUS.md`](../docs/BACKEND_IMPLEMENTATION_STATUS.md)。

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
- `POST /api/v1/agent/chat/stream?granularity=character`（SSE 逐字输出）
- `POST /api/v1/confirmations`
- `GET /docs`

移动端的响应、JWT、图片直传、数据库边界与 Agent SSE 接入规则见
[`docs/MOBILE_API_CONTRACT.md`](../docs/MOBILE_API_CONTRACT.md)。

## Agent 模型配置

Agent 支持 DeepSeek 与智谱 GLM，通过 `NXTREP_LLM_PROVIDER` 切换：

```env
# DeepSeek（默认）
NXTREP_LLM_PROVIDER=deepseek
NXTREP_DEEPSEEK_API_KEY=your-deepseek-api-key
NXTREP_DEEPSEEK_MODEL=deepseek-v4-flash
NXTREP_DEEPSEEK_THINKING_ENABLED=false

# 切换到 GLM 时
NXTREP_LLM_PROVIDER=glm
NXTREP_GLM_API_KEY=your-zhipu-api-key
NXTREP_GLM_MODEL=glm-5.1
NXTREP_GLM_VISION_MODEL=glm-4.6v-flash
NXTREP_EMBEDDING_PROVIDER=glm
NXTREP_GLM_EMBEDDING_MODEL=embedding-3
NXTREP_EMBEDDING_DIMENSIONS=1024
NXTREP_EMBEDDING_BATCH_SIZE=64
NXTREP_EMBEDDING_TIMEOUT_SECONDS=45
NXTREP_EMBEDDING_MAX_RETRIES=2
NXTREP_RAG_ENABLED=false
NXTREP_RAG_CANDIDATE_K=20
NXTREP_RAG_TOP_K=5
NXTREP_GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
NXTREP_LLM_TEMPERATURE=0.2
NXTREP_LLM_TIMEOUT_SECONDS=45
NXTREP_LLM_MAX_RETRIES=2
NXTREP_AGENT_INTENT_ROUTER_TIMEOUT_SECONDS=12
NXTREP_AGENT_INTENT_ROUTER_MAX_RETRIES=0
NXTREP_VISION_TEMPERATURE=0.1
NXTREP_VISION_TIMEOUT_SECONDS=60
```

`NXTREP_GLM_VISION_MODEL` 专门用于食物和身体图片理解，不受
`NXTREP_LLM_PROVIDER` 的文本模型切换影响。
DeepSeek V4 默认开启思考模式；本项目默认关闭它，以兼容意图路由的结构化输出，
并缩短移动端首字等待时间。只有确认当前工具调用链能够完整回传思考内容时才建议开启。
`NXTREP_GLM_EMBEDDING_MODEL` 专门用于RAG查询和知识分块向量化；生成模型与
Embedding模型相互独立。当前统一使用1024维，已经写入的知识向量不得混用其他维度。
模型厂商适配集中在 `providers/models.py`；Agent 运行时只依赖模型网关。
如果 DeepSeek 和 GLM 文本密钥同时配置，另一家会作为只读模型调用、意图路由、
摘要和最终回复的备用模型。带写副作用的 ReAct 分支不会自动重跑，避免重复创建草稿。
意图路由继续按主、备模型切换，但使用独立的短超时且默认不在单个模型内部重试，
避免网络故障时被通用的 `45 秒 × 2 次重试` 策略阻塞；普通 ReAct、摘要和最终回复仍使用
`NXTREP_LLM_TIMEOUT_SECONDS` 与 `NXTREP_LLM_MAX_RETRIES`。

不要把真实 API Key 提交到 Git；本地密钥只写入已忽略的 `.env`。

验证Embedding配置和真实返回维度：

```bash
uv run python -m nxtrep_backend.cli.check_embeddings
```

该检查只输出模型名和维度，不输出测试文本、向量值或API Key。

## RAG数据库前置条件

RAG使用PostgreSQL的`vector`扩展和Python `pgvector`包。服务器扩展必须由数据库管理员
在每个目标数据库中启用一次，应用账号不应拥有超级用户权限：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

本地`nxtrep`数据库当前使用`vector 0.8.6`。知识库表按来源、文档版本、文本块、Embedding
四层保存；迁移只检查扩展，不会以应用账号创建或在回滚时删除扩展。`NXTREP_RAG_ENABLED`
仍保持`false`，直到正式知识资料完成授权审核和 RAG 固定评测。摄取流水线、混合检索、
Agent Tool、引用测试以及 PostgreSQL 17 + pgvector 0.8.6 隔离实例端到端验收已经完成。

## RAG 知识资料工作流

所有命令都从 `backend` 目录运行。先确认数据库迁移和 Embedding 配置正常：
正式来源的审核结论、许可依据和允许回答范围见
[`docs/RAG_KNOWLEDGE_SOURCES.md`](../docs/RAG_KNOWLEDGE_SOURCES.md)。

```bash
uv run alembic upgrade head
uv run python -m nxtrep_backend.cli.check_embeddings
```

知识资料只接受 PDF、HTML 或 XHTML。先对本地文件试运行；该步骤只解析、清洗和切块，
不会调用 GLM，也不会写入数据库：

```bash
uv run python -m nxtrep_backend.cli.import_knowledge \
  --file data/knowledge_sources/raw/hhs-2018-physical-activity-guidelines-2nd-en.pdf \
  --source-key hhs-2018-physical-activity-guidelines-2nd \
  --title "Physical Activity Guidelines for Americans, 2nd edition" \
  --topic training \
  --locale en \
  --content-type application/pdf \
  --dry-run
```

确认资料的发布者和授权允许项目使用后，登记一个默认未激活的来源：

```bash
uv run python -m nxtrep_backend.cli.register_knowledge_source \
  --source-key hhs-2018-physical-activity-guidelines-2nd \
  --title "Physical Activity Guidelines for Americans, 2nd edition" \
  --source-type url \
  --source-uri "https://odphp.health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines/current-guidelines" \
  --publisher "U.S. Department of Health and Human Services" \
  --license-name "ODPHP public domain" \
  --topic training \
  --locale en
```

保存命令输出的 `source_id`，再正式导入。正式导入会生成 Embedding，并输出后续审核需要的
`document_id`：

```bash
uv run python -m nxtrep_backend.cli.import_knowledge \
  --source-id <source-uuid> \
  --file data/knowledge_sources/raw/hhs-2018-physical-activity-guidelines-2nd-en.pdf \
  --source-key hhs-2018-physical-activity-guidelines-2nd \
  --title "Physical Activity Guidelines for Americans, 2nd edition" \
  --topic training \
  --locale en \
  --content-type application/pdf
```

人工检查来源、正文、切块和授权信息后，依次审核并发布文档：

```bash
uv run python -m nxtrep_backend.cli.review_knowledge_document \
  --document-id <document-uuid>
uv run python -m nxtrep_backend.cli.publish_knowledge_document \
  --document-id <document-uuid>
```

使用只读调试命令验证召回结果、分数、匹配方式和引用位置：

```bash
uv run python -m nxtrep_backend.cli.search_knowledge \
  --query "成年人一周应该安排多少有氧活动和力量训练？" \
  --topic training \
  --source-key hhs-2018-physical-activity-guidelines-2nd \
  --candidate-k 20 \
  --top-k 5
```

只有正式资料通过检索和评测后，才能在本地 `.env` 中设置
`NXTREP_RAG_ENABLED=true`。来源登记、导入、审核和发布不能省略；未发布文档不会进入在线检索。
开关关闭时，`knowledge_retrieval` 分支会在调用文本模型前返回不可重试的
`RAG_UNAVAILABLE`，不会退化为使用模型记忆回答知识事实。

## Agent 流式连接

流式接口在没有业务事件时每 15 秒发送一次 `: heartbeat` SSE 注释，并每秒检查一次
客户端是否断开。客户端断开后会关闭 LangGraph 流，把尚未完成的 `AgentRun` 标记为
`cancelled`，且不会保存不完整的助手回复。两个间隔可以配置：

```env
NXTREP_AGENT_SSE_HEARTBEAT_SECONDS=15
NXTREP_AGENT_SSE_DISCONNECT_POLL_SECONDS=1
```

浏览器应忽略以冒号开头的 SSE 心跳，只处理带 `event:` 和 `data:` 的业务事件。

## 图片存储配置

开发环境使用香港地域的阿里云 OSS 私有 Bucket：

```env
NXTREP_STORAGE_PROVIDER=aliyun_oss
NXTREP_OSS_REGION=cn-hongkong
NXTREP_OSS_ENDPOINT=https://oss-cn-hongkong.aliyuncs.com
NXTREP_OSS_USE_CNAME=false
NXTREP_OSS_BUCKET=your-private-bucket
NXTREP_OSS_ACCESS_KEY_ID=your-ram-access-key-id
NXTREP_OSS_ACCESS_KEY_SECRET=your-ram-access-key-secret
NXTREP_OSS_OBJECT_PREFIX=images
NXTREP_OSS_UPLOAD_URL_EXPIRE_SECONDS=600
NXTREP_OSS_DOWNLOAD_URL_EXPIRE_SECONDS=300
NXTREP_IMAGE_MAX_BYTES=10485760
```

AccessKey 必须来自只获授权到该 Bucket `images/*` 前缀的 RAM 用户。配置会在
图片存储功能实际使用时按需校验；密钥不会写入 `.env.example` 或日志。

图片存储基础设施使用阿里云 OSS Python SDK V2，并提供：随机对象 Key、V4 PUT/GET
预签名、类型/大小限制、禁止覆盖以及上传后的 HeadObject 元数据校验。业务接口只依赖
`ImageStorageProvider`，不会直接调用 OSS SDK。

使用随机不存在的对象执行只读连通性检查：

```bash
uv run python -m nxtrep_backend.cli.check_oss
```

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

## 扩展结构化食品库

食品营养数字存 PostgreSQL，不属于 RAG。CSV 列为：

```text
external_id,name,brand,region,state,basis_amount_g,kcal,protein_g,carbs_g,fat_g,confidence,aliases
```

`aliases` 使用 `|` 分隔。先试运行校验，再正式导入：

```bash
uv run python -m nxtrep_backend.cli.import_food_catalog --file foods.csv --source usda --dry-run
uv run python -m nxtrep_backend.cli.import_food_catalog --file foods.csv --source usda
```

重复导入相同营养值不会生成新版本；数字变化时新增 `FoodVersion`，保留来源和历史。

## 主动教练检查（需用户开启）

用户在 App 的「今天」页开启主动教练后，系统可基于已记录的训练日历、训练后疲劳和
饮食记录缺口生成站内建议。默认关闭；没有饮食记录不等于没有进食。检查只创建可标记
已读的站内通知，不自动修改训练计划或饮食数据；重复检查不会创建重复通知。

App 打开「今天」页时会触发一次检查。若要在用户未打开 App 时按日检查，需要在部署环境
中另行配置定时器，按中国时区每天运行：

```bash
uv run python -m nxtrep_backend.cli.run_proactive_review
```

可用 `--date YYYY-MM-DD` 检查指定日期（例如在测试环境中复现）；定时器本身未随项目部署。
也可将以下命令作为**独立、受进程管理器监护的 worker** 运行，无需依赖用户打开 App。
本地开发命令为：

```bash
uv run python -m nxtrep_backend.cli.run_proactive_worker --at 08:00
```

复用后端 Docker 镜像时，将启动命令覆盖为
`python -m nxtrep_backend.cli.run_proactive_worker --at 08:00`。

`--at` 使用 `Asia/Shanghai` 的 24 小时制时间，默认 `08:00`；失败默认 15 分钟后开始
指数退避重试，最长间隔 6 小时，可用 `--retry-minutes` 调整初始间隔。启动时若已过当天
执行时间，会立即补跑当天；重启后可能
再次检查同一天，但通知按日期/类型去重。进程运行期间会保留失败日期并重试，且不会
因此阻塞次日检查；若进程长期停机，恢复后只自动补跑当天，不回放所有停机日。
不要把 worker 嵌入每个 Uvicorn worker，也不要与另一套定时器同时部署；建议只运行
一个受监护的实例。复用 Web Docker 镜像时须覆盖默认启动命令，并禁用其 HTTP 健康检查。
这项 MVP 不发送系统推送，通知仅在 App 内展示。
用户可对每条建议反馈「有帮助」「不相关」或「内容不准」；反馈保留在通知及审计事件中，
用于后续评估，不会在当前版本中自动改变训练计划或个性化规则。用户主动选择讨论建议时，
会进入现有 Agent 会话；若需要实际变更，仍须经过待确认草稿，不能直接执行。
如果将「饮食记录缺口」评价为「不相关」或「内容不准」，这类提醒会从反馈当日起暂停
7 个中国时区自然日；改评为「有帮助」可恢复，期满也会自动恢复。该规则不会屏蔽
训练日历或高疲劳提醒，也不会修改任何训练、饮食记录。
主动教练按中国时区检查日期计数：通常每天最多新建 2 条站内建议，依次优先处理
高疲劳、未完成训练、饮食记录缺口。若较晚补录的高疲劳记录出现，即使已达上限，
仍可追加一条恢复提醒。App 可选择「仅训练与恢复」或「包含饮食记录」；此范围会影响
后续新提醒和当前建议列表，不会删除历史通知。

## Agent 固定评测与监控

非 RAG 文本评测集可以直接运行。该命令会真实调用当前配置的模型并写入测试会话，
因此需要传入数据库中已存在的测试用户 UUID：

```bash
uv run python -m nxtrep_backend.cli.evaluate_agent --user-id <test-user-uuid>
```

图片评测集不会把真实照片或 OSS ID 提交进仓库。复制
`evaluation/datasets/asset_fixtures.example.json` 为 `asset_fixtures.local.json`，将其中值替换为
该测试用户拥有且已经完成上传的 `asset_id`，然后运行：

```bash
uv run python -m nxtrep_backend.cli.evaluate_agent \
  --user-id <test-user-uuid> \
  --dataset src/nxtrep_backend/evaluation/datasets/image_agent.template.json \
  --asset-fixtures src/nxtrep_backend/evaluation/datasets/asset_fixtures.local.json \
  --output agent-evaluation-report.json
```

RAG 评测模板已经写入首批来源预期的 `source_key@1`。资料发布后先核对实际版本；如果目标
数据库不是首次导入，复制为本地文件并将 `required_knowledge_source_ids` 改为实际发布的
`source_key@version`，然后在启用 RAG 的测试环境运行：

```powershell
Copy-Item `
  src/nxtrep_backend/evaluation/datasets/rag_agent.template.json `
  src/nxtrep_backend/evaluation/datasets/rag_agent.local.json
```

```bash
uv run python -m nxtrep_backend.cli.evaluate_agent \
  --user-id <test-user-uuid> \
  --dataset src/nxtrep_backend/evaluation/datasets/rag_agent.local.json \
  --output rag-agent-evaluation-report.json
```

评分器检查任务路由、响应状态、草稿确认规则、知识来源版本、禁止出现的错误码和危险表述。
运行监控通过
`nxtrep.agent` logger 记录开始、节点完成、成功、失败、取消和毫秒耗时；不记录聊天正文、
图片内容、对象地址或模型隐式推理。

## 当前状态

后端功能代码已经完成，OpenAPI 当前包含 169 个路径、204 个操作和 224 个 Schema。
数据库迁移头为 `e4b7c2a9d851`。训练接口支持暂停/继续、有效训练时长和组间计时恢复。
发布前仍需为目标环境配置 PostgreSQL + pgvector、
安全 JWT、显式 CORS 来源，以及按需配置模型和 OSS 密钥；外部服务未配置时相关接口会
安全失败，不影响普通数据库业务接口启动。
