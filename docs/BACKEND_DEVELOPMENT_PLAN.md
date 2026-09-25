# NxtRep 后端开发设计

> 依据：`PRD.md`  
> 范围：FastAPI + LangChain 后端；暂不开发 Flutter。  
> 本文保留技术架构、完整接口设计和 Agent/RAG 设计，不包含开发分工。
> 用户界面遵循 [`SIMPLIFIED_PRODUCT_EXPERIENCE.md`](SIMPLIFIED_PRODUCT_EXPERIENCE.md)：
> 后端保留同步、版本、审计和 Agent 编排能力，但前端默认隐藏这些技术细节。
>
> 实施状态（2026-09-12）：后端范围已经实现并通过完整测试；本文的“建议实现顺序”仅保留为
> 历史设计顺序。当前能力、验证结果和部署前置条件以
> [`BACKEND_IMPLEMENTATION_STATUS.md`](BACKEND_IMPLEMENTATION_STATUS.md) 为准。

## 1. 技术架构

### 1.1 技术栈

| 领域 | 技术 |
|---|---|
| Python 与依赖 | Python 3.12+、uv、`pyproject.toml`、`uv.lock` |
| HTTP API | FastAPI、Uvicorn、Pydantic 2 |
| 数据库 | PostgreSQL 16+、SQLAlchemy 2 async、asyncpg、Alembic |
| Agent | LangChain 1.x `create_agent`，底层使用 LangGraph runtime |
| 模型适配 | 独立 LangChain provider 包，如 `langchain-openai` |
| RAG | PostgreSQL Full Text Search + pgvector；不单独引入向量数据库 |
| 鉴权 | Argon2id 密码哈希、短期 JWT access token、可撤销 refresh token |
| 外部请求 | HTTPX |
| 测试与检查 | pytest、pytest-asyncio、Ruff |
| 文件 | S3 兼容对象存储，用于身体照片、食物照片和动作媒体 |
| 后台任务 | PostgreSQL job table + 独立 worker；后续有需要再引入 Redis |

### 1.2 架构形式

采用模块化单体，一个代码库运行 API 和 worker：

```text
Flutter（后续）
  └─ HTTPS / JSON / SSE
      └─ FastAPI
          ├─ accounts / profiles
          ├─ exercises / training / calendar
          ├─ nutrition / body / progress
          ├─ agent / confirmations / memories
          ├─ sync / exports / notifications
          ├─ PostgreSQL + pgvector
          ├─ object storage
          └─ LLM、食物库等外部 provider
```

建议目录：

```text
backend/src/nxtrep_backend/
├─ main.py
├─ api/                    # 路由、鉴权依赖、错误处理
├─ core/                   # 配置、安全、日志、幂等
├─ db/                     # session、base、migrations
├─ modules/
│  ├─ accounts/
│  ├─ profiles/
│  ├─ exercises/
│  ├─ training/
│  ├─ nutrition/
│  ├─ body/
│  ├─ progress/
│  ├─ agent/
│  ├─ confirmations/
│  ├─ sync/
│  └─ exports/
├─ agents/                 # graph、prompts、tools、RAG、schemas
├─ providers/              # LLM、food、storage、push adapters
└─ workers/                # 周报、导出、通知、清理任务
```

## 2. API 通用约定

- 业务前缀：`/api/v1`。
- 认证：`Authorization: Bearer <access_token>`。
- 时间统一保存 UTC，API 使用带时区 ISO 8601；用户另存 IANA 时区。
- 单位固定为 kg、cm、g、kcal；可计算数值使用 Decimal/Numeric。
- 用户资源必须通过 `(user_id, resource_id)` 查询；查询到他人资源也返回 404。
- 创建训练、记录组、保存饮食、确认执行、同步 push 等接口要求 `Idempotency-Key`。
- 可编辑资源包含递增 `version`，更新时提交 `expected_version`，冲突返回 409。
- 普通列表统一使用 `page/page_size` 分页；同步和消息历史等连续数据使用 cursor/sequence。
- 删除默认软删除；照片和账号永久删除由后台任务清理。

成功响应不强制套统一外壳，而是直接返回 OpenAPI 声明的强类型资源；分页结果通常使用
`list/total/page/page_size/has_more`，无响应体操作返回 `204 No Content`，Agent 流式接口返回
`text/event-stream`。这样可以保持普通 JSON、下载和流式传输各自正确的 HTTP 语义。

错误响应统一为：

```json
{
  "error": {
    "code": "EXERCISE_VERSION_CONFLICT",
    "message": "Exercise has been modified",
    "details": {"expected_version": 2, "current_version": 3}
  }
}
```

`details` 可省略；客户端按 `error.code` 分支，不匹配英文 `message`。完整的移动端认证、图片、
数据库隔离和 SSE 规则见 [`MOBILE_API_CONTRACT.md`](MOBILE_API_CONTRACT.md)。

## 3. 完整接口设计

阶段标记：M0=训练基础，M1=饮食与进展，M2=Agent 闭环，M3=稳定性，V1/V2=PRD 后续版本。

### 3.1 系统、账号与档案

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/api/v1/health` | API 前缀下的基础健康检查 | M0 |
| GET | `/health` | 不带 API 前缀的基础健康检查 | M0 |
| GET | `/health/live` | 进程存活检查 | M0 |
| GET | `/health/ready` | 数据库及必要依赖就绪检查 | M0 |
| POST | `/auth/login` | 密码登录，返回 access/refresh token | M0 |
| POST | `/auth/refresh` | 轮换 refresh token | M0 |
| POST | `/auth/logout` | 撤销当前 refresh session | M0 |
| POST | `/auth/password/setup` | 预创建账号首次设置密码 | M0 |
| POST | `/auth/password/change` | 修改密码并可撤销其他设备 session | M0 |
| GET | `/auth/sessions` | 查看当前账号登录设备 | M3 |
| DELETE | `/auth/sessions/{id}` | 撤销指定设备 session | M3 |
| GET | `/me` | 当前账号、初始化状态与权限 | M0 |
| GET | `/profile` | 获取个人档案、目标和限制 | M0 |
| PATCH | `/profile` | 修改基础档案，不改写历史 | M0 |
| GET | `/profile/goals-and-constraints` | 一次获取当前目标和全部限制 | M0 |
| PUT | `/profile/goals-and-constraints` | 一次更新目标和限制并检查版本 | M0 |
| GET | `/profile/goals` | 目标版本列表 | M0 |
| POST | `/profile/goal-drafts` | 创建目标修改草稿 | M0 |
| POST | `/profile/goal-check` | 检查期限、训练条件和目标冲突 | M0 |
| GET | `/profile/constraints` | 器械、动作、疼痛、过敏和饮食限制 | M0 |
| PUT | `/profile/constraints` | 整体更新限制，保留审计记录 | M0 |
| GET | `/settings` | 单位、时区、隐私和通知设置 | M0 |
| PATCH | `/settings` | 修改非高风险设置 | M0 |
| POST | `/admin/users` | 管理员预创建账号，不提供公开注册 | M0 |

### 3.2 动作库

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/exercises` | 搜索/筛选官方与个人动作 | M0 |
| GET | `/exercises/{id}` | 动作详情、肌群、器械、安全提示 | M0 |
| POST | `/exercises` | 创建自定义动作 | M0 |
| PATCH | `/exercises/{id}` | 修改自己的自定义动作 | M0 |
| DELETE | `/exercises/{id}` | 停用自定义动作，历史快照保留 | M0 |
| GET | `/exercises/{id}/history` | 个人历史表现和 PR 入口 | M0 |
| GET | `/exercises/{id}/substitutions` | 获取替代动作与原因 | M0 |
| POST | `/exercises/{id}/classification-drafts` | AI 生成分类建议草稿 | M0 |
| GET | `/exercise-media/{id}` | 获取动作图片/动效元数据和签名地址 | M0 |
| POST | `/exercise-content/{id}/feedback` | 反馈讲解或数据错误 | V1 |

### 3.3 训练模板、计划和版本

五种来源最终都生成相同 `PlanDraft`，确认后才生成或激活不可变 `PlanVersion`。

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/training/templates` | 官方模板列表与筛选 | M0 |
| GET | `/training/templates/{id}` | 模板详情 | M0 |
| POST | `/training/plan-drafts` | 手动创建计划草稿 | M0 |
| POST | `/training/plan-drafts/from-template` | 从官方模板创建草稿 | M0 |
| POST | `/training/plan-drafts:parse-text` | AI 解析文字版计划 | M0 |
| POST | `/training/plan-drafts:parse-image` | OCR/视觉模型解析截图 | M0 |
| POST | `/training/plan-drafts:generate` | 根据档案生成 AI 计划草稿 | M0 |
| GET | `/training/plan-drafts/{id}` | 获取草稿、歧义和缺失项 | M0 |
| PATCH | `/training/plan-drafts/{id}` | 用户校对草稿 | M0 |
| DELETE | `/training/plan-drafts/{id}` | 删除未确认草稿 | M0 |
| POST | `/training/plan-drafts/{id}/validate` | 执行器械、时长、安全和字段校验 | M0 |
| POST | `/training/plan-drafts/{id}/submit` | 生成创建/激活确认卡片 | M0 |
| GET | `/training/plans` | 计划列表 | M0 |
| GET | `/training/plans/active` | 当前生效计划 | M0 |
| GET | `/training/plans/{id}` | 计划概要 | M0 |
| GET | `/training/plans/{id}/versions` | 查看全部历史版本 | M0 |
| GET | `/training/plans/{id}/versions/{version}` | 查看不可变版本详情 | M0 |
| POST | `/training/plans/{id}/revision-drafts` | 基于某版本创建修改草稿 | M0 |
| POST | `/training/plans/{id}/archive-drafts` | 创建归档确认卡片 | M0 |

### 3.4 日历、漏练和临时调整

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/calendar` | 查询计划日期、实际日期和训练状态 | M0 |
| GET | `/calendar/events/{id}` | 单个计划事件详情 | M0 |
| POST | `/calendar/events` | 手动安排一次训练草稿 | M0 |
| POST | `/calendar/reschedule-drafts` | 生成顺延、合并或跳过候选 | M0 |
| POST | `/calendar/compression-drafts` | 按 15/30/45 分钟生成压缩方案 | V1 |
| POST | `/calendar/substitution-drafts` | 器械不可用时生成临时替代 | V1 |
| GET | `/calendar/reschedule-drafts/{id}` | 查看时长、训练量和后续影响 | M0 |
| POST | `/calendar/reschedule-drafts/{id}/submit` | 创建重排确认卡片 | M0 |

后端强制校验：合并最多增加 1 个主项或 2～3 个辅助动作、预计不超过 90 分钟、训练量最多增加 30%，疼痛/恢复差/肌群冲突时阻止合并。

### 3.5 训练执行与记录

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| POST | `/workouts` | 开始训练并保存计划快照 | M0 |
| GET | `/workouts/active` | 获取并恢复未结束训练 | M0 |
| GET | `/workouts` | 训练历史列表 | M0 |
| GET | `/workouts/{id}` | 训练详情和快照 | M0 |
| PATCH | `/workouts/{id}/pre-check` | 睡眠、精力、酸痛、疼痛、时间 | M0 |
| POST | `/workouts/{id}/exercises` | 临时添加动作 | M0 |
| POST | `/workouts/{id}/exercises/{item_id}/replace` | 替换当前动作并记录原因 | M0 |
| POST | `/workouts/{id}/exercises/{item_id}/skip` | 跳过动作 | M0 |
| POST | `/workouts/{id}/sets` | 幂等记录一组并立即提交 | M0 |
| PATCH | `/workouts/{id}/sets/{set_id}` | 修正组记录并产生 revision | M0 |
| DELETE | `/workouts/{id}/sets/{set_id}` | 作废组记录并保留痕迹 | M0 |
| POST | `/workouts/{id}/pause` | 标记暂停 | M0 |
| POST | `/workouts/{id}/resume` | 继续训练并累计暂停时长 | M0 |
| POST | `/workouts/{id}/finish` | 完成训练并记录反馈 | M0 |
| POST | `/workouts/{id}/abandon` | 放弃未完成部分，保留已完成记录 | M0 |
| GET | `/workouts/{id}/summary` | 训练事实、PR、疼痛和表现摘要 | M0 |
| POST | `/workouts/{id}/progression-drafts` | 生成下次进阶建议草稿 | M0 |
| POST | `/workouts/{id}/progression-drafts/{draft_id}/submit` | 提交进阶草稿并创建确认卡 | M0 |
| GET | `/workouts/{id}/revisions` | 查看历史修正记录 | V1 |

训练总计时由客户端根据 `started_at`、`paused_at` 和 `total_paused_seconds` 本地刷新；
服务端返回排除暂停时间的 `elapsed_seconds`。组间倒计时使用最近完成组的 `completed_at`
和动作快照中的 `rest_seconds` 恢复。客户端不得每秒请求服务端更新时间。

### 3.6 食物、饮食和营养目标

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/foods/search` | 聚合搜索 USDA、中国库、OFF 和自定义食物 | M1 |
| GET | `/foods/{id}` | 食物详情、来源、地区、生熟状态和可信度 | M1 |
| POST | `/foods` | 创建自定义食品 | M1 |
| PATCH | `/foods/{id}` | 修改自定义食品，新记录使用新版本 | M1 |
| DELETE | `/foods/{id}` | 停用自定义食品，历史营养快照保留 | M1 |
| GET | `/foods/frequent` | 常吃食物 | M1 |
| GET | `/foods/barcodes/{code}` | 查询包装食品条码 | V1 |
| POST | `/nutrition/entry-drafts:parse-text` | 解析自然语言食物记录 | M1 |
| POST | `/nutrition/entry-drafts:estimate-image` | 照片估算食物和区间 | M1 |
| GET | `/nutrition/entry-drafts/{id}` | 查看估算、追问和缺失项 | M1 |
| PATCH | `/nutrition/entry-drafts/{id}` | 用户修正食物、重量和营养 | M1 |
| POST | `/nutrition/entry-drafts/{id}/submit` | 创建保存确认卡片 | M1 |
| POST | `/nutrition/entries` | 保存已确认的营养快照 | M1 |
| GET | `/nutrition/entries` | 按日期/餐次查看记录 | M1 |
| GET | `/nutrition/entries/{id}` | 饮食记录详情 | M1 |
| PATCH | `/nutrition/entries/{id}` | 修改并保留 revision | M1 |
| DELETE | `/nutrition/entries/{id}` | 删除确认流程 | M1 |
| GET | `/nutrition/daily-summary` | 目标范围、已摄入和剩余量 | M1 |
| GET | `/nutrition/weekly-summary` | 周平均、记录完整度和自由餐 | M1 |
| POST | `/nutrition/advice` | 回答能不能吃、吃多少 | M1 |
| GET | `/nutrition/targets` | 当前及历史营养目标 | M1 |
| POST | `/nutrition/target-drafts` | 创建目标调整草稿 | M1 |
| POST | `/nutrition/target-drafts/{target_id}/submit` | 提交目标草稿并创建确认卡 | M1 |
| POST | `/nutrition/dynamic-target-drafts` | 基于至少 14 天趋势生成调整草稿 | V1 |
| GET | `/nutrition/flexible-meals` | 自由餐安排 | M1 |
| POST | `/nutrition/flexible-meals` | 安排自由餐 | M1 |
| PATCH | `/nutrition/flexible-meals/{id}` | 转移或修改自由餐 | M1 |
| GET | `/recipes` | 自定义菜谱列表 | V1 |
| POST | `/recipes` | 创建菜谱及份量 | V1 |
| GET | `/recipes/{id}` | 菜谱详情 | V1 |
| PATCH | `/recipes/{id}` | 修改菜谱，新记录使用新快照 | V1 |
| DELETE | `/recipes/{id}` | 停用菜谱 | V1 |

### 3.7 身体数据与照片

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| POST | `/body/measurements` | 记录体重、腰围和可选围度 | M1 |
| GET | `/body/measurements` | 查询原始身体数据 | M1 |
| GET | `/body/measurements/{id}` | 单条测量详情和来源 | M1 |
| PATCH | `/body/measurements/{id}` | 修正测量并留痕 | M1 |
| DELETE | `/body/measurements/{id}` | 删除确认流程 | M1 |
| POST | `/body/body-fat/navy` | 美军围度法估算区间 | M1 |
| POST | `/body/body-fat/manual` | 保存其他来源体脂值 | M1 |
| GET | `/body/body-fat` | 查看不同来源估算，不默认合并 | M1 |
| POST | `/body/photos/uploads` | 获取照片上传地址和授权说明 | M1 |
| POST | `/body/photos` | 完成照片登记 | M1 |
| GET | `/body/photos` | 照片列表，可隐藏敏感内容 | M1 |
| POST | `/body/photos/{id}/analysis-drafts` | 创建 AI 照片分析草稿 | M1 |
| POST | `/body/photos/compare` | 前后照片比较 | M1 |
| DELETE | `/body/photos/{id}` | 立即撤销访问并清理原图/派生物 | V1 |
| POST | `/body/progress-photos/uploads` | `/body/photos/uploads` 的兼容路径 | 兼容 |
| POST | `/body/progress-photos` | `/body/photos` 的兼容路径 | 兼容 |
| GET | `/body/progress-photos` | `/body/photos` 列表的兼容路径 | 兼容 |
| POST | `/body/progress-photos/{photo_id}/analysis-drafts` | 照片分析的兼容路径 | 兼容 |
| POST | `/body/progress-photos/compare` | 照片比较的兼容路径 | 兼容 |
| DELETE | `/body/progress-photos/{photo_id}` | 照片删除的兼容路径 | 兼容 |
| GET | `/media/images/capabilities` | 获取手机图片格式、大小、尺寸和直传能力 | M1 |
| POST | `/media/images/upload-intents` | 创建通用图片上传意图 | M1 |
| POST | `/media/images/{asset_id}/complete` | 完成通用图片登记与校验 | M1 |
| GET | `/media/images/{asset_id}/download-intent` | 为本人已处理完成的图片创建临时下载授权 | M1 |

### 3.8 进展、PR、趋势和报告

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/progress/overview` | 训练、饮食和身体概览 | M1 |
| GET | `/progress/training` | 次数、完成率、时长、训练量 | M1 |
| GET | `/progress/nutrition` | 热量、宏量和记录完整度趋势 | M1 |
| GET | `/progress/body` | 原始值与 7/14 天平滑趋势 | M1 |
| GET | `/progress/body-trend` | 身体趋势的兼容响应路径 | 兼容 |
| GET | `/progress/prs` | PR 列表 | M1 |
| GET | `/progress/prs/{id}` | 追溯到具体训练和组 | M1 |
| GET | `/progress/muscle-volume` | 肌群训练量分布 | V1 |
| GET | `/progress/recovery` | 恢复评分和变化 | V1 |
| GET | `/progress/correlations` | 跨模块“可能相关”分析 | V1 |
| GET | `/reports` | 周报、月报和阶段报告列表 | M1 |
| POST | `/reports/weekly` | 生成/重新生成 AI 周报 | M1 |
| POST | `/reports/monthly` | 生成月报 | V2 |
| POST | `/reports/phase` | 阶段总结与预测范围 | V2 |
| GET | `/reports/{id}` | 报告事实、缺失数据、建议与依据 | M1 |
| GET | `/alerts` | 多数据点确认后的异常提醒 | V1 |
| POST | `/alerts/{id}/dismiss` | 忽略异常提醒 | V1 |

### 3.9 Agent 会话、确认和 Memory

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| POST | `/agent/chat` | 兼容的单次非流式聊天入口 | M2 |
| POST | `/agent/chat/stream` | 兼容的单次 SSE 聊天入口 | M2 |
| POST | `/agent/proactive/review` | 经用户授权后检查近期记录并生成幂等站内建议 | M3 |
| PUT | `/agent/proactive/notices/{id}/feedback` | 用户评价主动建议的有用性或准确性 | M3 |
| POST | `/agent/conversations` | 新建空会话 | M2 |
| GET | `/agent/conversations` | 会话列表、置顶和归档筛选 | M2 |
| GET | `/agent/conversations/{id}` | 当前会话元数据 | M2 |
| PATCH | `/agent/conversations/{id}` | 重命名、置顶、归档 | M2 |
| DELETE | `/agent/conversations/{id}` | 删除会话，不删除全局 Memory | M2 |
| GET | `/agent/conversations/{id}/messages` | 当前会话消息历史 | M2 |
| POST | `/agent/conversations/{id}/messages` | 发送消息并通过 SSE 返回 Agent 事件 | M2 |
| POST | `/agent/runs/{id}:cancel` | 请求取消运行 | M2 |
| GET | `/agent/runs/{id}` | 查询运行、工具和错误状态 | M2 |
| GET | `/confirmations` | 待确认/历史确认卡片列表 | M2 |
| GET | `/confirmations/{id}` | 变更前后、理由、影响和状态 | M2 |
| POST | `/confirmations/{id}/approve` | 重新校验版本后执行一次 | M2 |
| POST | `/confirmations/{id}/reject` | 拒绝草稿 | M2 |
| POST | `/confirmations/{id}/cancel` | 取消尚未决定的草稿 | M2 |
| GET | `/memories` | 查看当前有效的全局 Memory | M2 |
| POST | `/memories` | 用户或 Agent 直接保存稳定 Memory | M2 |
| PATCH | `/memories/{id}` | 按版本直接修改 Memory | M2 |
| DELETE | `/memories/{id}` | 按版本软删除并立即从 Agent 上下文排除 | M2 |
| GET | `/agent/tool-runs` | 查看个人 Agent 工具调用审计 | M3 |

### 3.10 主动消息与通知

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| GET | `/notification-settings` | 总开关、分类、频率和免打扰 | M3 |
| PATCH | `/notification-settings` | 修改主动联系授权和设置 | M3 |
| GET | `/notifications` | App 内通知列表 | M3 |
| POST | `/notifications/{id}/read` | 标记已读 | M3 |
| POST | `/devices/push-tokens` | 注册 APNs token | M3 |
| DELETE | `/devices/push-tokens/{id}` | 撤销设备推送 | M3 |

设计目标：默认每天最多 2 条，同一问题 24 小时不重复，普通消息在免打扰期间延后，所有变更仍需确认。当前主动教练 MVP 仅生成幂等站内通知，不发送系统推送，也不自动执行变更；每日总量控制和免打扰延后仍待实现。

### 3.11 离线同步、冲突、导出和删除

| 方法 | 路径 | 功能 | 阶段 |
|---|---|---|---|
| POST | `/sync/push` | 批量上传本地变更和幂等键 | M3 |
| GET | `/sync/pull` | 按游标获取服务端变更和 tombstone | M3 |
| GET | `/sync/status` | 当前设备同步状态 | M3 |
| GET | `/sync/conflicts` | 冲突列表及两侧版本 | M3 |
| POST | `/sync/conflicts/{id}/resolve` | 选择本地、服务端或手动合并 | M3 |
| POST | `/exports` | 创建个人数据导出任务 | M3 |
| GET | `/exports` | 导出任务列表 | M3 |
| GET | `/exports/{id}` | 状态和限时下载地址 | M3 |
| GET | `/exports/{export_id}/download` | 下载已完成且未过期的导出文件 | M3 |
| POST | `/deletion-drafts` | 预览删除范围和恢复规则 | M3 |
| POST | `/deletion-drafts/{id}/confirm` | 二次确认后执行删除 | M3 |
| GET | `/audit-events` | 查看自己的重要数据变更 | M3 |

### 3.12 内部管理与 RAG 知识库

生产环境建议通过 CLI 或严格管理员权限开放：

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/admin/knowledge/sources` | 登记知识来源及版权/版本信息 |
| POST | `/admin/knowledge/sources/{id}/ingest` | 解析、切块、embedding 和建索引 |
| GET | `/admin/knowledge/sources` | 查看索引状态和版本 |
| POST | `/admin/knowledge/search` | 调试混合检索、过滤和引用结果 |
| POST | `/admin/knowledge/sources/{id}/deactivate` | 停用来源并从在线检索排除 |
| DELETE | `/admin/knowledge/sources/{id}` | 删除来源、chunks 和向量 |
| POST | `/admin/knowledge/documents/{document_id}/review` | 审核知识文档并保存结果 |
| POST | `/admin/knowledge/documents/{document_id}/publish` | 发布已审核文档及检索版本 |
| GET | `/admin/jobs` | 查看后台任务 |
| POST | `/admin/jobs/{id}/retry` | 重试失败任务 |

## 4. Agent 设计结构

### 4.1 基本原则

- Agent 是自然语言入口，不是数据库管理员。
- 训练、饮食、身体等用户数据通过结构化工具读取，不通过 RAG 猜测。
- RAG 只检索动作讲解、训练原则、食品说明和产品帮助等非结构化知识。
- Agent 可创建 draft/confirmation，但没有直接修改正式业务表的工具。
- `user_id` 由认证上下文绑定，不作为 LLM 可填写参数。
- 任何工具或事务失败都必须返回失败，Agent 不得声称操作成功。

### 4.2 请求执行图

```text
authenticate
  → load_conversation
  → classify_intent
  → build_minimal_context
  → select_tools
  → agent_loop
       ├─ structured read tools
       ├─ deterministic calculation tools
       ├─ RAG retrieval tool
       └─ draft tools
  → safety/output validation
  → persist message + tool audit
  → stream final event / confirmation card
```

LangChain `create_agent` 负责模型—工具循环；业务服务负责认证、数据权限、确认状态机和事务。Agent 运行状态不能代替业务数据库状态。

### 4.3 会话上下文与隔离

每次请求最多包含：

1. 当前会话最近消息。
2. 当前会话自己的压缩摘要。
3. 当前任务需要的 App 结构化数据。
4. 用户当前有效且未删除的全局 Memory。
5. 必要的 RAG 知识片段及来源。

新会话不继承旧会话原文或摘要。删除聊天不自动删除 Memory；删除 Memory 后，下一次 context build 必须立即不可见。会话摘要保存覆盖到的最后消息 ID，模型推测不得写入摘要事实区。

### 4.4 Agent 工具

只读工具：

- `read_profile_summary`
- `read_active_goal`
- `read_constraints`
- `read_active_training_plan`
- `read_calendar`
- `read_recent_workouts`
- `read_exercise_history`
- `read_daily_nutrition_summary`
- `search_food_candidates`
- `read_body_trends`
- `read_memories`
- `read_confirmation_status`

确定性计算工具：

- `validate_goal`
- `validate_training_plan`
- `evaluate_reschedule_constraints`
- `calculate_workout_volume_change`
- `calculate_pr_candidates`
- `calculate_progression_bounds`
- `calculate_nutrition_remaining`
- `calculate_navy_body_fat_range`
- `calculate_smoothed_trend`

草稿工具：

- `create_training_plan_draft`
- `create_schedule_change_draft`
- `create_progression_draft`
- `create_nutrition_entry_draft`
- `create_nutrition_target_draft`
- `save_memory`
- `update_memory`
- `delete_memory`

知识工具：

- `retrieve_knowledge(query, topic, locale, source_keys)`：统一检索动作教学、训练原则、
  营养知识、产品帮助和安全资料。

工具由 intent 和权限动态选择，模型不会在一次请求中默认看到所有工具。

### 4.5 RAG 设计

#### 使用范围

适合进入 RAG：

- 经过审核的动作步骤、呼吸、常见错误和安全提示。
- 官方训练模板说明和训练原则。
- 经过审核的营养知识、食物数据源说明和估算误差说明。
- NxtRep 产品帮助、隐私说明和功能文档。

不进入 RAG：

- 用户档案、训练记录、饮食记录、身体数据和当前目标。
- token、密码、密钥、原始身体照片。
- 需要精确计算的 PR、热量剩余、训练量和体脂公式结果。

#### 存储结构

PostgreSQL 启用 pgvector，主要表：

- `knowledge_sources`：标题、来源 URL/文件、版权、locale、版本、状态、校验 hash。
- `knowledge_documents`：标准化正文、主题、审核状态、发布时间。
- `knowledge_chunks`：chunk 文本、章节路径、metadata、全文检索向量。
- `knowledge_embeddings`：chunk id、embedding model/version、vector。

#### 索引流程

```text
source registration
  → parse and normalize
  → remove duplicate content
  → semantic chunking
  → attach metadata and source anchors
  → embedding
  → full-text + vector index
  → quality check
  → publish version
```

知识发布前需要审核。更新来源生成新版本；报告和回答保存使用的 chunk/source/version，旧回答仍可追溯。

#### 检索流程

1. 根据任务确定 `topic`、`locale`、风险级别和允许来源。
2. PostgreSQL 全文检索与 pgvector 相似度检索并行执行。
3. 合并去重并按 metadata 过滤：`status=published`、locale、主题、适用人群。
4. 对少量候选重排。
5. 返回 3～6 个最相关片段、来源标题、章节和版本。
6. Agent 只能根据检索证据回答知识性事实；没有足够证据时明确说明。

RAG 结果不授予写权限。检索到的文本即使包含指令，也只作为不可信资料，不得改变 system policy 或工具权限。

### 4.6 结构化输出

以下任务强制使用 Pydantic schema：

- 文字/截图训练计划解析。
- 自然语言/照片饮食解析。
- 训练计划、漏练重排和进阶草稿。
- 可直接保存的稳定 Memory 候选。
- 周报、月报和调整建议。

统一包含：`result`、`ambiguities`、`missing_fields`、`assumptions`、`confidence`、`evidence_refs`。关键字段缺失或存在歧义时标记 `needs_review=true`，不能静默猜测或自动执行。

### 4.7 Confirmation 状态机

```text
draft → pending → approved → executing → succeeded
          ├─ rejected
          ├─ cancelled
          └─ expired
                         executing → failed
```

Confirmation 保存操作类型、变更前后、理由、影响、目标资源版本、过期时间和执行结果。

批准时必须：锁定 confirmation、检查状态与过期时间、重新校验资源版本/权限/安全规则、在事务中执行命令和审计、提交后才返回 `succeeded`。资源已变化时返回 `VERSION_CONFLICT`，重新生成草稿。

### 4.8 Memory

Memory 保存当前用户明确且稳定的长期信息：长期目标、器械条件、固定训练时间、过敏忌口、动作限制和沟通偏好。新增、修改和删除不创建确认卡片，但必须在 Agent 回复中明确告知结果。

不保存一次性情绪、当天疲劳、临时聚餐、假设、否定事实、第三方信息，以及可直接从 App 读取的临时状态。不确定时先追问。每条 Memory 包含类别、内容、来源、保存时间、版本和删除时间；服务层负责用户隔离、精确重复抑制、乐观版本校验和软删除。

### 4.9 Agent SSE 事件

`POST /agent/conversations/{id}/messages` 返回：

- `message.started`
- `message.delta`
- `tool.started`
- `tool.completed`
- `confirmation.created`
- `message.completed`
- `error`

每个事件包含 `request_id`、`agent_run_id`、`conversation_id`、`message_id` 和递增 `sequence`。断线后客户端读取已保存的完整消息；MVP 不要求从任意 token 精确续传。

### 4.10 Agent 安全与测试

- 测试跨用户读取、旧会话泄漏、删除 Memory 后继续读取等隔离问题。
- 测试用户要求绕过确认、伪造 user_id 和 prompt injection。
- 测试工具失败、模型超时和结构化输出不合法时安全失败。
- 固定评估样例包括计划解析、疼痛优先、食物估算区间、数据不足和周报证据。
- Prompt、模型、工具和 RAG 索引都记录版本，但日志不保存密码、token、照片或无关隐私数据。

## 5. 关键数据结构

- 账号：`users`、`credentials`、`refresh_sessions`、`profiles`、`goal_versions`、`constraints`
- 动作：`exercises`、`exercise_aliases`、`exercise_substitutions`、`exercise_snapshots`
- 计划：`training_plans`、`plan_versions`、`plan_drafts`、`plan_days`、`plan_exercises`
- 训练：`calendar_events`、`workout_sessions`、`workout_snapshots`、`workout_exercises`、`workout_sets`、`record_revisions`、`prs`
- 饮食：`foods`、`food_versions`、`nutrition_entry_drafts`、`nutrition_entries`、`nutrition_snapshots`、`nutrition_targets`、`recipes`
- 身体：`body_measurements`、`body_fat_estimates`、`body_photos`
- Agent：`conversations`、`messages`、`conversation_summaries`、`agent_runs`、`tool_runs`、`memories`
- 变更：`confirmations`、`command_executions`、`audit_events`、`idempotency_records`
- RAG：`knowledge_sources`、`knowledge_documents`、`knowledge_chunks`、`knowledge_embeddings`
- 稳定性：`sync_changes`、`sync_cursors`、`sync_conflicts`、`background_jobs`、`exports`

训练计划、训练执行和饮食记录均保留版本或快照，后续资料更新不得静默改写历史。

## 6. 历史实现顺序（已完成）

1. uv、配置、统一响应/错误、PostgreSQL、Alembic、真实鉴权。
2. 档案、动作库、计划草稿/版本、训练快照和组记录。
3. Confirmation 状态机和计划激活/进阶执行。
4. LangChain 基础会话、结构化工具和文字计划解析。
5. 饮食、身体数据、趋势、PR 和周报。
6. Agent 完整工具、Memory 和 RAG。
7. 离线同步、主动消息、导出删除和图片分析能力。
