# NxtRep 后端项目结构与入门开发指南

> 目标：读完后能知道代码应该放在哪里，并能照着现有结构完成一个普通接口。接口字段和数据库表的详细对应见 `BACKEND_INTERFACE_SCHEMA_DATABASE_GUIDE.md`。
> 当前实现与验证结果见 [`BACKEND_IMPLEMENTATION_STATUS.md`](BACKEND_IMPLEMENTATION_STATUS.md)。

## 1. 技术栈和设计思路

| 技术 | 在项目中的用途 |
|---|---|
| FastAPI | 注册 HTTP 路由、依赖注入、生成 OpenAPI 文档。 |
| Pydantic | 定义请求/响应 Schema，在业务执行前校验数据。 |
| SQLAlchemy Async | 用 Python Model 查询 PostgreSQL，所有 I/O 使用 `async/await`。 |
| PostgreSQL | 持久化数据；使用 JSONB、约束、索引和行锁。 |
| Alembic | 记录数据库结构变更，让不同环境按相同顺序升级。 |
| Pytest | Schema、Service、Route 和真实数据库集成测试。 |
| Ruff | 代码格式和静态规则检查。 |
| LangChain/LangGraph | Agent 意图路由、分支执行、工具编排、模型适配和流式响应。 |

项目采用分层结构：

```text
Router -> Schema -> Service -> Repository -> Model/PostgreSQL
```

分层的原因不是为了文件多，而是把不同问题分开：

- Router 只关心 HTTP。
- Schema 只关心输入输出是否合法。
- Service 只关心业务规则。
- Repository 只关心怎样查数据库。
- Model 只关心数据怎样保存和约束。

这样业务规则可以脱离 HTTP 单独测试，SQL 也不会散落在每个接口中。

## 2. 项目整体结构

```text
NxtRep/
├─ PRD.md                         产品需求
├─ docs/                          项目设计和开发文档
└─ backend/
   ├─ pyproject.toml              Python 项目、依赖和工具配置
   ├─ uv.lock                     锁定依赖版本
   ├─ .env.example                环境变量示例
   ├─ alembic.ini                 数据库迁移配置
   ├─ migrations/                 Alembic 迁移脚本
   ├─ src/nxtrep_backend/         后端正式源码
   │  ├─ main.py                  FastAPI 应用入口
   │  ├─ api/                     HTTP 层
   │  ├─ schemas/                 Pydantic 输入输出
   │  ├─ services/                业务规则
   │  ├─ repositories/            数据访问
   │  ├─ db/                      数据库连接和模型
   │  ├─ core/                    配置、安全、令牌、时区
   │  ├─ cli/                     本地管理命令
   │  ├─ agents/                  Agent 路由、工作流、节点和工具
   │  ├─ domain/                  早期领域对象/兼容代码
   │  └─ modules/                 未来垂直模块化说明
   └─ tests/                      自动化测试
```

## 3. 仓库根目录

| 文件夹/文件 | 做什么 | 为什么放这里 |
|---|---|---|
| `PRD.md` | 产品目标、用户流程和功能范围。 | 先回答“为什么做”，不是代码细节。 |
| `docs/BACKEND_API_SPEC.md` | API 契约。 | 供前后端约定路径和 JSON。 |
| `docs/BACKEND_DEVELOPMENT_PLAN.md` | 早期后端开发计划。 | 保留实施过程；当前完成情况要以代码和本指南为准。 |
| `docs/BACKEND_INTERFACE_SCHEMA_DATABASE_GUIDE.md` | 接口、Schema、Service 和表的对应关系。 | 查具体字段时使用。 |
| `docs/BACKEND_PROJECT_STRUCTURE_GUIDE.md` | 当前这份结构和入门指南。 | 查“代码写在哪里、为什么”时使用。 |
| `.git/`、`.gitattributes` | Git 版本管理和文本规则。 | 不属于业务代码。 |

## 4. `backend/`：独立后端工程

| 文件/目录 | 用途 |
|---|---|
| `pyproject.toml` | 包名、Python 版本、FastAPI/SQLAlchemy/Pydantic 等依赖，以及 pytest/ruff 配置。 |
| `uv.lock` | 精确锁定依赖版本，使不同电脑安装一致。不要手工编辑。 |
| `.env.example` | 可提交的环境变量模板；真实 `.env` 不应提交。 |
| `README.md` | 启动提示。部分早期接口描述可能落后，正式行为以代码和新文档为准。 |
| `alembic.ini` | Alembic 的脚本目录和日志配置。 |
| `migrations/` | 数据库结构版本。Model 改了不等于数据库已经改了，必须配套 migration。 |
| `src/` | 使用 src-layout 保存正式包，避免测试误导入仓库根目录中的同名文件。 |
| `tests/` | 自动化测试，不与生产代码混在一起。 |

不要提交 `.env`、缓存、数据库日志或 IDE 私有配置。

## 5. `src/nxtrep_backend/main.py`：应用入口

`create_app()` 完成四件事：

1. 读取 `Settings`。
2. 创建 `FastAPI`。
3. 注册 CORS 和统一异常处理。
4. 以 `/api/v1` 前缀挂载 `api_router`。

`app = create_app()` 是 Uvicorn 启动时导入的对象。`lifespan()` 以后可以初始化缓存、对象存储等共享客户端；当前只是预留。

## 6. `api/`：HTTP 边界

### 6.1 顶层文件

| 文件 | 用途 | 关键点 |
|---|---|---|
| `api/router.py` | 汇总所有子 Router，并添加 `/auth`、`/training` 等前缀。 | 新建路由文件后必须在这里 `include_router`，否则接口不会出现。 |
| `api/deps.py` | 定义 `DbSession`、`CurrentUser` 等依赖。 | 鉴权在这里统一完成，业务 Router 不重复解析 JWT。 |
| `api/errors.py` | `ApiError` 和全局异常处理器。 | 统一返回 `{error:{code,message,details}}`，不要在各接口发明不同错误格式。 |
| `api/idempotency.py` | 读取 `Idempotency-Key`，封装 begin/replay/complete。 | 多个写接口复用同一套幂等流程。 |
| `api/routes/` | 按业务域保存实际接口函数。 | Router 应保持薄：解析、调用、映射，不堆复杂业务。 |

### 6.2 `api/routes/` 每个文件

| 文件 | 接口范围 | 调用的核心 Service |
|---|---|---|
| `health.py` | `/api/v1/health` | 无数据库，简单探活。 |
| `auth.py` | 登录、刷新、首次设密 | `AccountService` |
| `profile.py` | 档案、目标和约束 | `ProfileService`、`GoalsService` |
| `exercise.py` | 动作查询、自定义动作增改删 | `ExercisesService`、`IdempotencyService` |
| `training.py` | 模板、计划草稿、验证、提交、活动版本 | `TrainingService` |
| `calendar.py` | 日历查询和改期草稿 | 复用 `TrainingService` |
| `workout.py` | 实际训练、组记录、动作替换、结束、渐进草稿 | `WorkoutService` |
| `nutrition.py` | 食物、餐食和营养目标 | `NutritionService` |
| `body.py` | 身体测量、体脂、进度和 PR | `BodyService` |
| `confirmations.py` | 待确认列表、批准和拒绝 | `DatabaseConfirmationService` |
| `agent.py` | Agent 聊天入口 | `AgentService`，当前未正式配置。 |
| `__init__.py` | 标记 Python 包。 | 通常不写业务。 |

### 6.3 Router 应该写什么

一个 Router 函数通常只做：

```python
@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(
    body: ItemCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ItemResponse:
    repository = SqlAlchemyItemRepository(session)
    service = ItemService(repository)
    item = await service.create(user.id, body)
    return ItemResponse.model_validate(item, from_attributes=True)
```

路径、Query、Header、HTTP 状态码和业务异常转 `ApiError` 放 Router；计算规则和状态变化放 Service。

## 7. `schemas/`：请求和响应的数据形状

Pydantic Schema 不是数据库表。它是 API 边界的合同：

- Request Schema：客户端允许传什么。
- Response Schema：服务端承诺返回什么。
- `Field(...)`：长度、大小、精度和必填规则。
- `field_validator`：只校验/规范一个字段。
- `model_validator`：校验多个字段之间的关系。
- `extra="forbid"`：拒绝未声明字段。
- `from_attributes=True`：允许从 SQLAlchemy Model 生成响应。

### 7.1 文件分类

| 文件 | 主要 Schema |
|---|---|
| `auth.py` | 登录、刷新令牌、首次设密、Token 响应。 |
| `profile.py` | 个人档案读取和部分更新。 |
| `goals.py` | 目标、器械、动作偏好、伤病、饮食限制。 |
| `exercise.py` | 动作筛选、创建、更新、详情和替代动作。 |
| `training.py` | 计划日/动作嵌套输入、草稿、版本、日历和改期。 |
| `workout.py` | 训练前检查、组记录、完成反馈、渐进建议。 |
| `nutrition.py` | 食物营养、餐食项目、营养目标和每日汇总。 |
| `body.py` | 身体测量、Navy 体脂、趋势、PR。 |
| `confirmation.py` | 提交确认、批准/拒绝和列表响应。 |
| `error.py` | 全局错误响应格式。 |
| `admin.py` | 本地管理员创建用户相关数据形状；当前不是公开注册接口。 |
| `agent.py` | Agent 对话请求/响应骨架。 |

### 7.2 为什么不能只靠数据库校验

数据库约束是最后防线，但返回的错误不适合客户端阅读。Schema 能在执行 SQL 前返回准确的 `422`，例如：

```python
class RangeRequest(BaseModel):
    minimum: Decimal = Field(ge=0)
    maximum: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def check_order(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self
```

关键规则最好同时存在于 Schema 和数据库约束中：前者提供体验，后者保护数据。

## 8. `services/`：业务规则中心

Service 不直接接收 HTTP Request，也不决定状态码。它接收已经校验的数据和 Repository，完成业务状态变化。

| 文件/类 | 负责什么 |
|---|---|
| `account.py / AccountService` | 预创建账号、密码哈希、失败次数与锁定、JWT/刷新令牌。 |
| `profile.py / ProfileService` | 档案的部分更新和版本冲突。 |
| `goals.py / GoalsService` | 目标版本化、约束更新、动作可见性和警告。 |
| `exercise.py / ExercisesService` | 动作查询、自定义动作写入、肌群同步和软删除。 |
| `training.py / TrainingService` | 计划草稿、模板复制、计划验证、确认提交、版本激活和日历改期。 |
| `workout.py / WorkoutService` | 训练快照、组记录、修订、动作替换、训练结束、PR 和渐进方案。 |
| `nutrition.py / NutritionService` | 食物版本、营养换算、餐食快照、每日汇总和目标版本。 |
| `body.py / BodyService` | 身体数据修订、体脂公式、趋势平滑和进度汇总。 |
| `confirmation.py / DatabaseConfirmationService` | 锁定确认单、检查版本和过期、分发已批准命令。 |
| `idempotency.py / IdempotencyService` | 请求哈希、认领 key、判断重放、保存稳定响应。 |
| `agent_workflow.py` 与 `agent_handlers/` | Agent 会话执行、分支处理、结果合并和持久化。 |

### 8.1 Service 的常见写法

```python
class ItemService:
    def __init__(self, repository: SqlAlchemyItemRepository) -> None:
        self.repository = repository

    async def update(self, user_id: UUID, item_id: UUID, body: UpdateRequest):
        item = await self.repository.get(user_id, item_id, lock=True)
        if item is None:
            raise ItemNotFoundError()
        if item.version != body.expected_version:
            raise ItemConflictError(current_version=item.version)

        item.name = body.name
        item.version += 1
        await self.repository.session.flush()
        return item
```

为什么用 `flush()` 而不是到处 `commit()`：一次请求内可能同时修改多个表；提交由 `DbSession` 的事务统一完成，任一步异常都能整体回滚。

## 9. `repositories/`：数据库查询集中地

Repository 将 SQLAlchemy 查询从 Service 中抽离。它应该负责：

- 根据 `user_id` 做租户隔离。
- 查询、分页、排序和聚合。
- 更新前按需 `SELECT ... FOR UPDATE`。
- 保存 Model 和审计行。
- 使用 `flush()` 取得数据库生成的 ID，但不擅自结束整个请求事务。

### 9.1 文件对应

| 文件 | 主要查询对象 |
|---|---|
| `user.py` | `users`、`credentials`、`profiles`、`refresh_sessions`。 |
| `profile.py` | `profiles`。 |
| `goals.py` | `user_goals`、`user_constraints`，以及动作可见性。 |
| `exercise.py` | 动作主表、别名、肌群、替代动作。 |
| `training.py` | 模板、草稿、活动版本、版本历史、日历和改期草稿。 |
| `workout.py` | workout 聚合、训练动作、组、修订、渐进草稿和 PR。 |
| `nutrition.py` | 食物版本、餐食、修订和营养目标。 |
| `body.py` | 身体测量、体脂、进度聚合和 PR 查询。 |
| `confirmation.py` | 确认单的创建、锁定、分页和过期处理。 |
| `idempotency.py` | 幂等 key 的并发认领和响应保存。 |

### 9.2 最重要的安全习惯

错误示例：

```python
select(Workout).where(Workout.id == workout_id)
```

正确示例：

```python
select(Workout).where(
    Workout.id == workout_id,
    Workout.user_id == user_id,
)
```

只凭资源 ID 查询可能读取到其他用户的数据；因此 Repository 方法通常把 `user_id` 放在第一个业务参数。

## 10. `db/`：数据库基础设施和表模型

### 10.1 顶层文件

| 文件 | 用途 |
|---|---|
| `db/base.py` | `Base`、统一约束命名、UUID `IdMixin`、时间戳 `TimestampMixin`。 |
| `db/session.py` | 创建异步 Engine 和 SessionFactory；每个请求开启一个事务。 |
| `db/models/__init__.py` | 导出所有模型，确保 Alembic 能发现 metadata。 |
| `db/models/` | SQLAlchemy 表映射。 |

### 10.2 `db/models/` 文件

| 文件 | 表 |
|---|---|
| `account.py` | `users`、`credentials`、`profiles`、`refresh_sessions` |
| `goals.py` | `user_goals`、`user_constraints` |
| `exercise.py` | `exercises`、`exercise_muscles`、`exercise_aliases`、`exercise_substitutions`、`exercise_media` |
| `training.py` | `training_templates`、`training_plan_drafts`、`training_plan_versions`、`calendar_events`、`calendar_reschedule_drafts` |
| `workout.py` | `workouts`、`workout_exercises`、`workout_sets`、`workout_set_revisions`、`progression_drafts`、`personal_records` |
| `nutrition.py` | `foods`、`food_versions`、`nutrition_entries`、`nutrition_entry_revisions`、`nutrition_target_drafts`、`nutrition_target_versions` |
| `body.py` | `body_measurements`、`body_measurement_revisions`、`body_fat_estimates` |
| `confirmation.py` | `confirmations` |
| `idempotency.py` | `idempotency_records` |

Model 负责列类型、外键、索引、唯一约束和 CheckConstraint。不要在 Model 中编排复杂业务流程。

### 10.3 普通列和 JSONB 怎么选

使用普通列：经常筛选、排序、关联或需要严格数据库类型的值，如 `user_id/status/started_at/version`。

使用 JSONB：需要保留完整快照、内部结构一起读写、以后可能增加可选字段的值，如：

- 计划 `days`
- 餐食 `items/totals`
- 训练前检查 `pre_check`
- 动作目标 `target_snapshot`
- 修改前后 `old_values/new_values`

JSONB 不是“无需设计”；对应嵌套结构仍应通过 Pydantic 和 Service 校验。

## 11. `migrations/`：让数据库跟上 Model

| 文件/目录 | 用途 |
|---|---|
| `env.py` | 读取 SQLAlchemy metadata 和数据库配置。 |
| `script.py.mako` | 新迁移文件模板。 |
| `versions/*.py` | 按 revision 顺序执行的升级/降级脚本。 |

当前迁移大致按以下顺序建立：账号档案、目标约束、动作库、幂等记录、剩余业务表、官方模板种子、日历快照补丁。

常用命令：

```powershell
uv run alembic upgrade head
uv run alembic check
uv run alembic revision --autogenerate -m "add item table"
```

自动生成后必须人工检查 migration，尤其是 JSONB、部分唯一索引、循环外键和数据迁移。

## 12. `core/`：跨业务基础能力

| 文件 | 用途 |
|---|---|
| `config.py` | `Settings` 从 `.env` 读取数据库、JWT、CORS 和 OpenAI 配置；带 `NXTREP_` 前缀。 |
| `security.py` | 密码哈希、令牌哈希等安全工具。 |
| `tokens.py` | 创建和解析访问令牌、刷新令牌相关工具。 |
| `timezones.py` | 统一中国时区，避免日报/训练日期因 UTC 跨日。 |
| `__init__.py` | 包标记。 |

这些能力可以被多个业务域使用，但不应放具体的训练或营养规则。

## 13. `cli/`：本地管理命令

`cli/create_user.py` 用于预创建账号，因为产品不开放公开注册：

```powershell
uv run python -m nxtrep_backend.cli.create_user --username demo --set-password
```

它复用 `AccountService`，而不是绕过业务层直接插表；这样 CLI 与 API 的密码规则保持一致。

`schemas/admin.py` 同时服务于已注册的管理员用户和知识库维护接口；所有管理员接口都会
检查当前账号的 `is_admin`。

## 14. `agents/`：Agent 正式实现

| 文件 | 当前内容 | 当前状态 |
|---|---|---|
| `prompts.py` | 健身助手系统规则和安全边界。 | 正式运行提示词。 |
| `factory.py`、`graph.py`、`nodes.py` | 构建 LangGraph、多标签分支和汇总节点。 | 已接入运行路径。 |
| `tools/` | 请求级绑定 `user_id` 的训练、饮食、身体、Memory、知识和确认工具。 | 使用正式 Service/Repository。 |
| `api/routes/agent.py` | `/agent/chat`、SSE、会话、运行和工具审计入口。 | 会话与 Run 持久化已完成。 |
| `services/agent_handlers/` | 训练、饮食、身体、知识和普通问答分支。 | 已接入结构化输出与安全检查。 |

工具按请求绑定 `user_id`，Agent 不直接获得不受约束的数据库写权限；高影响修改会先生成
草稿和 confirmation。RAG 只检索已审核发布来源，功能是否启用由部署环境配置决定。

## 15. `domain/` 和 `modules/`

| 目录 | 说明 |
|---|---|
| `domain/confirmation.py` | 早期纯内存 confirmation 领域对象，主要被旧兼容类引用；公开接口现在使用数据库版 `Confirmation` 和 `DatabaseConfirmationService`。新功能优先沿用数据库版结构。 |
| `modules/README.md` | 记录未来按垂直业务模块组织的设想。当前项目实际采用横向分层目录，因此不要同时创建第二套重复实现。 |

这两个目录都不是当前普通接口的首选落点。

## 16. `tests/`：怎样验证代码

测试文件按能力命名，而不是建立一个巨大的 `test_all.py`：

| 类型 | 示例 | 验证内容 |
|---|---|---|
| Schema 测试 | `test_exercise_schemas.py` | 合法输入通过，边界和字段组合失败。 |
| Service 单元测试 | `test_exercise_service.py` | 使用 Fake Repository 验证业务规则，不依赖 HTTP。 |
| Repository 测试 | `test_exercise_repository.py` | 查询条件、分页、保存行为。 |
| Route 测试 | `test_exercise_route.py` | 路径、依赖、状态码、错误格式和响应。 |
| 数据库集成测试 | `test_*_database_integration.py` | PostgreSQL 约束、事务、锁、JSONB 和真实查询。 |
| 契约测试 | `test_remaining_route_contract.py` | 所需方法和路径是否注册。 |

常用命令：

```powershell
uv run pytest
uv run ruff check .
uv run alembic check
```

低风险字段修改至少跑相关测试；表、事务、幂等或跨域流程修改应跑完整测试和迁移检查。

## 17. 用现有结构写一个接口：完整步骤

假设要新增“删除一条身体测量”接口。

### 第一步：先写行为，不急着写代码

明确：

- 路径：`DELETE /api/v1/body/measurements/{measurement_id}`
- 只能删除当前用户自己的记录。
- 需要 `expected_version` 防止误删刚被更新的数据。
- 是软删还是硬删，是否保留审计；这会影响 Model 和迁移。
- 返回 `204` 还是删除后的对象。

### 第二步：设计数据库

若选择软删除，在 `BodyMeasurement` 增加：

```python
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

随后创建 Alembic migration。以后所有正常查询都要排除 `deleted_at is not null`。

### 第三步：设计 Schema

若版本放 Query，可以复用 `expected_version: int = Query(ge=1)`；若还需要删除原因，定义：

```python
class BodyMeasurementDeleteRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)
```

Schema 负责“格式是否合法”，不负责查询记录是否属于用户。

### 第四步：写 Repository

```python
async def get_measurement(
    self,
    user_id: UUID,
    measurement_id: UUID,
    *,
    lock: bool = False,
):
    statement = select(BodyMeasurement).where(
        BodyMeasurement.id == measurement_id,
        BodyMeasurement.user_id == user_id,
        BodyMeasurement.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    return await self.session.scalar(statement)
```

### 第五步：写 Service

```python
async def delete_measurement(self, user_id, measurement_id, expected_version):
    item = await self.repository.get_measurement(
        user_id, measurement_id, lock=True
    )
    if item is None:
        raise BodyNotFoundError("Body measurement not found")
    if item.version != expected_version:
        raise BodyConflictError("Measurement changed", item.version)
    item.deleted_at = datetime.now(UTC)
    item.version += 1
    await self.repository.session.flush()
```

Service 负责归属后的业务判断、版本和状态变化。

### 第六步：写 Router

```python
@body_router.delete("/measurements/{measurement_id}", status_code=204)
async def delete_body_measurement(
    measurement_id: UUID,
    expected_version: Annotated[int, Query(ge=1)],
    user: CurrentUser,
    session: DbSession,
) -> None:
    try:
        await _service(session).delete_measurement(
            user.id, measurement_id, expected_version
        )
    except RuntimeError as exc:
        _raise_body_error(exc)
```

### 第七步：测试

至少测试：

1. `expected_version<1` 返回 422。
2. 当前用户能删除自己的数据。
3. 其他用户看不到这条数据。
4. 版本不一致返回 409 和当前版本。
5. 删除后普通列表不返回它。
6. 事务失败时删除状态回滚。

这就是本项目普通接口的完整开发闭环。

## 18. 四个重要机制为什么存在

### 18.1 乐观锁 `expected_version`

解决“后提交的人覆盖先提交的人”。读取响应中的 `version`，修改时原样带回；成功后版本加一。

### 18.2 幂等键 `Idempotency-Key`

解决网络超时和移动端离线重试。创建请求可能已经成功，但客户端没收到响应；用相同 key 重试会返回第一次结果，不会重复创建。

### 18.3 快照和不可变版本

训练计划、动作名称和食物营养以后会变化。历史训练/餐食必须保留发生当时的数据，所以保存 `days/items/name_snapshot/target_snapshot`，活动方案则用新版本替代旧版本。

### 18.4 confirmation

高影响操作分两步：先生成可展示的 before/after 草稿，用户批准后再执行。审批和真实修改在同一个事务里，失败整体回滚。

## 19. 新人最容易犯的错误

- 在 Router 里直接写复杂 SQL 和业务计算。
- 只按 `id` 查询，不带 `user_id`。
- 修改 Model 后忘记生成 migration。
- 每个 Repository 方法都 `commit()`，导致一个请求无法整体回滚。
- 更新接口不带 `expected_version`。
- 创建接口没有幂等键，移动端重试生成重复数据。
- 历史记录只保存外键，没有保存快照。
- 把 Pydantic Schema 当成数据库 Model，或者直接把数据库对象无控制地返回。
- 只测正常情况，不测越权、冲突、重复请求和事务失败。

## 20. 推荐阅读顺序

1. `main.py` 和 `api/router.py`：理解应用怎样挂载接口。
2. 选一个简单域，例如 `profile`，按 `route -> schema -> service -> repository -> model` 阅读。
3. 阅读 `exercise`：学习列表、创建、更新、软删除、幂等和版本冲突。
4. 阅读 `workout`：学习聚合、快照、审计和事务。
5. 阅读 `confirmation`：学习高影响操作的两阶段执行。
6. 对照同名测试，自己增加一个小接口并完整跑测试。

不要先从 Agent 开始。先掌握一个普通数据库接口的完整闭环，再进入 LangChain、RAG 和 Memory，会更容易理解和排错。
