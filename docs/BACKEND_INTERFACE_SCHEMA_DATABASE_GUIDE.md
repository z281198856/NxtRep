 # NxtRep 后端接口、Schema 与数据库对应手册

> 面向后端入门开发者。内容覆盖公开接口、主要请求/响应 Schema、核心 Service 方法和数据库表。
> Agent/LangChain、RAG、图片与平台能力现已实现；完整的当前状态见
> [`BACKEND_IMPLEMENTATION_STATUS.md`](BACKEND_IMPLEMENTATION_STATUS.md)。若本手册的逐项清单与
> OpenAPI 不一致，以运行中的 `/openapi.json` 为准。
> 移动端接入还必须遵守 [`MOBILE_API_CONTRACT.md`](MOBILE_API_CONTRACT.md)。

## 1. 先理解一次请求怎样流动

```text
客户端 HTTP 请求
  -> Router：读取路径、查询、Header 和 JSON，请求鉴权
  -> Pydantic Schema：检查类型、范围和字段组合
  -> Service：执行业务规则、版本检查和事务内操作
  -> Repository：组织 SQL，只读取当前用户的数据
  -> SQLAlchemy Model：映射 PostgreSQL 表和约束
  -> Response Schema：整理后返回 JSON
```

例如创建一条饮食记录：

```text
POST /api/v1/nutrition/entries
  -> NutritionEntryCreateRequest
  -> NutritionService.create_entry(user_id, body)
  -> SqlAlchemyNutritionRepository.add_entry(...)
  -> nutrition_entries
  -> NutritionEntryResponse
```

## 2. 所有接口都会遇到的参数

| 参数/类型 | 来自哪里 | 含义 |
|---|---|---|
| `Authorization: Bearer ...` | Header | 登录后的访问令牌。除健康检查和认证接口外，业务接口都用它确定当前用户。 |
| `CurrentUser` / `user` | FastAPI 依赖注入 | 不是客户端 JSON 字段；由令牌解析出的 `User`，Service 通常只接收 `user.id`。 |
| `DbSession` / `session` | FastAPI 依赖注入 | 当前请求共用的数据库事务。正常结束提交，异常时回滚。 |
| `Idempotency-Key` | Header，UUID | 写接口的客户端请求编号。同一用户、同一 key、同一请求可安全重试；结果保存在 `idempotency_records`。 |
| `expected_version` | Body 或 Query，整数 `>=1` | 乐观锁。客户端提交自己看到的版本；数据库版本不同就返回 `409`，避免覆盖别人刚修改的数据。 |
| `*_id` | Path 或 Body，UUID | 资源主键。Repository 查询时同时带 `user_id`，防止跨用户读取。 |
| `page` / `page_size` | Query | 页码默认 1；每页通常默认 20，范围 1～100。 |
| `start_date` / `end_date` | Query，`YYYY-MM-DD` | 查询日期区间，开始日期不能晚于结束日期。 |
| `datetime` 字段 | JSON，ISO 8601 | `started_at`、`eaten_at` 等必须包含时区，例如 `2026-08-27T08:30:00+08:00`。 |
| `Decimal` | JSON 数字 | 重量、营养和围度使用十进制数，避免浮点误差。 |
| `extra="forbid"` | Schema 配置 | 请求多传未定义字段时直接返回 `422`，尽早发现拼写错误。 |

### 常见返回字段

| 字段 | 含义 |
|---|---|
| `id` | 当前记录的 UUID。 |
| `version` | 当前资源版本，后续修改时作为 `expected_version`。 |
| `status` | 资源生命周期状态，例如 `editing`、`submitted`、`active`、`completed`。 |
| `list/total/page/page_size/has_more` | 标准分页结果。 |
| `created_at/updated_at` | 多数表通过公共 Mixin 自动记录，未必全部暴露给接口。 |

普通成功响应直接返回上表所述的强类型对象，不额外套 `data`；无内容操作返回 `204`。
所有非流式错误统一为 `{"error":{"code":"...","message":"...","details":...}}`，其中
`details` 可省略。客户端只依赖 `code` 做逻辑判断。

数据库连接只存在于后端配置和 Repository 层，不属于任何 API Schema。移动端不能携带数据库
连接串或直接执行 SQL，只能通过带 Bearer Token 的 HTTPS API 访问用户数据。

## 3. 认证接口 `/api/v1/auth`

### 3.1 接口、函数和表

| 接口 | Router 函数 -> Service 方法 | 请求/查询 | 主要数据库表 |
|---|---|---|---|
| `POST /auth/login` | `login` -> `AccountService.login` | `LoginRequest` | `users`、`credentials`、`refresh_sessions` |
| `POST /auth/refresh` | `refresh_tokens` -> `AccountService.refresh_tokens` | `RefreshTokenRequest` | `refresh_sessions`、`users` |
| `POST /auth/password/setup` | `setup_password` -> `AccountService.setup_password` | `PasswordSetupRequest` | `users`、`credentials`、`profiles`、`refresh_sessions` |

### 3.2 请求 Schema 参数

| Schema.字段 | 校验 | 用途与表字段 |
|---|---|---|
| `LoginRequest.username` | 去首尾空格，1～64 字符 | 登录名，对应 `users.username`，数据库做不区分大小写唯一约束。 |
| `LoginRequest.password` | 1～128 字符 | 明文只用于校验，不落库；与 `credentials.password_hash` 比较。 |
| `LoginRequest.device_name` | 可空，最长 120；空字符串转 `null` | 标识登录设备，写入 `refresh_sessions.device_name`。 |
| `RefreshTokenRequest.refresh_token` | 32～512 字符 | 刷新令牌；服务端只保存哈希到 `refresh_sessions.token_hash`。 |
| `PasswordSetupRequest.username` | 同登录名 | 找到预创建账号。 |
| `PasswordSetupRequest.setup_token` | 32～512 字符 | 首次设密令牌；哈希与有效期在 `credentials`。 |
| `PasswordSetupRequest.new_password` | 8～128 字符 | 哈希后写入 `credentials.password_hash`。 |

`TokenPairResponse` 返回 `access_token`、`refresh_token`、固定的 `token_type="bearer"`、
`expires_in`、`refresh_expires_in`，以及用户的
`id/username/password_setup_required`。Token 接口带 `Cache-Control: no-store`；refresh token
每次使用后轮换，移动端必须串行刷新并把新 token 安全写入 Keychain/Keystore。

## 4. 个人档案和目标 `/api/v1/profile`

### 4.1 接口对应

| 接口 | Router -> Service | Schema/参数 | 表 |
|---|---|---|---|
| `GET /profile` | `get_profile` | 无 Body | `users`、`profiles` |
| `PATCH /profile` | `update_profile` -> `ProfileService.update_profile` | `ProfileUpdateRequest` | `profiles` |
| `GET /profile/goals-and-constraints` | `get_goals_and_constraints` -> `GoalsService.get_goals_and_constraints` | 无 Body | `user_goals`、`user_constraints` |
| `PUT /profile/goals-and-constraints` | `update_goals_and_constraints` -> `GoalsService.update_goals_and_constraints` | `GoalsAndConstraintsUpdateRequest` | `user_goals`、`user_constraints`、读取 `exercises` |

### 4.2 `ProfileUpdateRequest`

至少提供一个可修改字段；未知字段被拒绝。

| 字段 | 校验 | 表对应与含义 |
|---|---|---|
| `display_name` | 可空，最长 80，空白转 `null` | `profiles.display_name`，用户展示名称。 |
| `sex` | `male/female/other/unspecified` | `profiles.sex`，用于体脂公式等；传空会规范为 `unspecified`。 |
| `birth_date` | 不能是未来日期 | `profiles.birth_date`。 |
| `height_cm` | `>0` 且 `<=300`，最多两位小数 | `profiles.height_cm`。 |
| `experience_level` | `beginner/intermediate/advanced` | `profiles.experience_level`。 |
| `weekly_training_days` | 0～7 | `profiles.weekly_training_days`，期望训练频率。 |
| `session_duration_minutes` | 1～1440 | `profiles.session_duration_minutes`，单次可用时长。 |
| `expected_version` | `>=1`，必填 | 对照并更新 `profiles.version`。 |

`ProfileResponse` 额外返回 `timezone` 和新 `version`。

### 4.3 `GoalsAndConstraintsUpdateRequest`

| 字段 | 校验 | 表对应与含义 |
|---|---|---|
| `goal_type` | 增肌、减脂保肌、重组、维持、力量之一 | 新版本写入 `user_goals.goal_type`。 |
| `target_date` | 可空，不能早于今天 | `user_goals.target_date`。 |
| `target_weight_kg` | `>0`、`<=500` | `user_goals.target_weight_kg`。 |
| `equipment` | 最多 50 个，小写代码、不可重复 | 整体存入 `user_constraints.equipment` JSONB。 |
| `preferred_exercises` | 最多 100 个 UUID、不可重复 | JSONB `preferred_exercise_ids`；写入前验证动作对该用户可见。 |
| `disliked_exercises` | 最多 100 个 UUID、不可重复 | JSONB `disliked_exercise_ids`；不能与偏好动作重叠。 |
| `pain_or_injuries` | 最多 50 项 | JSONB `pain_or_injuries`。每项包含 `kind`、`body_part`、可选 `severity(1～10)`、`notes(<=500)`。 |
| `allergies` | 最多 100 项，单项 1～100 字符 | JSONB `allergies`。 |
| `dietary_preferences` | 同上 | JSONB `dietary_preferences`。 |
| `expected_version` | 新建时可空；已有目标时必须与当前版本一致 | 控制 `user_goals.version` 和 `user_constraints.version` 的一致更新。 |

旧的 `user_goals` 不覆盖，而是变为 `superseded`；新行变为 `active`，因此可以追踪目标历史。

## 5. 动作库 `/api/v1/exercises`

### 5.1 接口对应

| 接口 | Router -> Service | 参数/Schema | 读写表 |
|---|---|---|---|
| `GET /exercises` | `list_exercises` -> `ExercisesService.list_exercises` | `ExerciseListQuery` | `exercises`、`exercise_aliases`、`exercise_muscles` |
| `GET /exercises/{exercise_id}` | `get_exercise_detail` -> `get_exercise_detail` | Path `exercise_id` | 上述表 + `exercise_substitutions` |
| `POST /exercises` | `create_custom_exercise` -> `create_custom_exercise` | `ExerciseCreateRequest` + 幂等 Header | `exercises`、`exercise_muscles`、`idempotency_records` |
| `PATCH /exercises/{exercise_id}` | `update_custom_exercise` -> `update_custom_exercise` | `ExerciseUpdateRequest` | `exercises`、`exercise_muscles` |
| `DELETE /exercises/{exercise_id}` | `delete_custom_exercise` -> `delete_custom_exercise` | Query `expected_version>=1` | `exercises.deleted_at/version`；软删除 |

### 5.2 查询和写入字段

| Schema.字段 | 校验 | 表对应/用途 |
|---|---|---|
| `ExerciseListQuery.keyword` | 可空，去空格，1～120 | 搜索 `exercises.name_zh` 和 `exercise_aliases.normalized_alias`。 |
| `equipment` / `muscle` | 小写代码，1～40 | 分别过滤 `exercises.equipment`、`exercise_muscles.muscle_code`。 |
| `page/page_size` | `page>=1`，每页 1～100 | 分页，不落库。 |
| `ExerciseCreateRequest.name_zh` | 1～120 | `exercises.name_zh`。 |
| `equipment` | 代码格式 `[a-z0-9_-]` | `exercises.equipment`。 |
| `primary_muscles` | 1～50、不可重复 | 多行写入 `exercise_muscles`，`role=primary`。 |
| `secondary_muscles` | 0～50、不可重复 | 多行写入 `exercise_muscles`，`role=secondary`；不能与主要肌群重叠。 |
| `notes` | 可空，最长 1000 | `exercises.notes`。 |
| `ExerciseUpdateRequest.*` | 字段规则同创建；至少修改一项 | 只更新明确传入的字段。 |
| `ExerciseUpdateRequest.expected_version` | `>=1` | 对照 `exercises.version`；成功后版本加一。 |

官方动作的 `owner_user_id=null`；自定义动作写当前 `user_id`。用户只能修改和软删除自己的自定义动作。详情响应中的动作说明、呼吸、错误、安全提示来自 `exercises` 的 JSONB，别名、肌群和替代动作来自关系表。

## 6. 训练计划 `/api/v1/training`

### 6.1 接口对应

| 接口 | Router -> Service/Repository | Schema/参数 | 表 |
|---|---|---|---|
| `GET /training/templates` | `list_templates` -> Repository | Query `goal_type/days_per_week/equipment` | `training_templates` |
| `POST /training/plan-drafts` | `create_plan_draft` -> `create_manual_draft` | `PlanDraftCreateRequest` + 幂等 | `training_plan_drafts`、`exercises`、`idempotency_records` |
| `POST /training/plan-drafts/from-template` | `create_plan_draft_from_template` -> `create_from_template` | `PlanDraftFromTemplateRequest` + 幂等 | `training_templates`、`training_plan_drafts`、`idempotency_records` |
| `GET /training/plan-drafts/{draft_id}` | `get_plan_draft` -> `get_draft` | Path `draft_id` | `training_plan_drafts` |
| `PATCH /training/plan-drafts/{draft_id}` | `update_plan_draft` -> `update_draft` | `PlanDraftUpdateRequest` | `training_plan_drafts`、读取 `exercises` |
| `POST /training/plan-drafts/{draft_id}/validate` | `validate_plan_draft` -> `validate_draft` | `ExpectedVersionRequest` | `training_plan_drafts`、`exercises` |
| `POST /training/plan-drafts/{draft_id}/submit` | `submit_plan_draft` -> `submit_draft` | `ExpectedVersionRequest` + 幂等 | `training_plan_drafts`、`confirmations`、`idempotency_records` |
| `GET /training/plans/active` | `get_active_plan` | 无 Body | `training_plan_versions` |
| `GET /training/plans/{plan_id}/versions` | `list_plan_versions` | Path + 分页 | `training_plan_versions` |

### 6.2 计划嵌套 Schema

`PlanDraftCreateRequest.days` 和数据库 `training_plan_drafts.days`、`training_plan_versions.days` 都是完整 JSONB 快照。

| Schema.字段 | 校验 | 含义/表内位置 |
|---|---|---|
| `name` | 1～120 | 草稿/计划名称。 |
| `weekly_frequency` | 1～7，必须等于 `days` 数量 | 每周训练几天。 |
| `days` | 1～7 项 | 整体写入 `*.days` JSONB。 |
| `PlanDayInput.day_index` | 1～7，草稿内唯一 | 第几个训练日，不一定是星期几。 |
| `PlanDayInput.name` | 1～120 | 训练日名称。 |
| `estimated_minutes` | 1～300 | 预计用时。 |
| `exercises` | 列表 | 当天动作快照。 |
| `exercise_id` | UUID | 引用可见的 `exercises.id`。 |
| `order_no` | `>=1`，同一天唯一 | 动作顺序。 |
| `target_sets` | 1～20 | 目标组数。 |
| `rep_min/rep_max` | 1～100，且最小不大于最大 | 目标次数区间。 |
| `target_load_kg` | 可空，`>=0` | 目标重量。 |
| `target_rir` | 可空，0～10 | 还可完成几次（Reps In Reserve）。 |
| `rest_seconds` | 可空，0～1800 | 组间休息秒数。 |

其他请求：

| Schema | 字段 | 含义 |
|---|---|---|
| `PlanDraftFromTemplateRequest` | `template_id`、可选 `name` | 复制 `training_templates.days` 为可编辑草稿；可覆盖名称。 |
| `PlanDraftUpdateRequest` | 可选 `name/weekly_frequency/days` + 必填 `expected_version` | 部分更新草稿；Service 再检查频率和天数一致、动作可用。 |
| `ExpectedVersionRequest` | `expected_version>=1` | 校验或提交前防止使用旧草稿。 |

提交不会直接激活：草稿状态变为 `submitted`，同时创建 `operation_type=training_plan_activate` 的 `confirmations`。用户批准后才生成不可变的 `training_plan_versions`，旧活动版本变为 `superseded`，并重建未来日历。

## 7. 日历 `/api/v1/calendar`

| 接口 | Router -> Service/Repository | 参数 | 表 |
|---|---|---|---|
| `GET /calendar` | `get_calendar` -> `list_calendar` | `start_date/end_date` | `calendar_events` |
| `POST /calendar/reschedule-drafts` | `create_reschedule_draft` -> `create_reschedule_draft` | `RescheduleDraftCreateRequest` + 幂等 | `calendar_events`、`calendar_reschedule_drafts`、`idempotency_records` |
| `POST /calendar/reschedule-drafts/{draft_id}/submit` | `submit_reschedule_draft` -> `submit_reschedule` | `ExpectedVersionRequest` + 幂等 | `calendar_reschedule_drafts`、`confirmations`、`idempotency_records` |

| 字段 | 校验 | 含义/表对应 |
|---|---|---|
| `missed_event_id` | UUID | 要调整的 `calendar_events.id`。只能处理尚未完成/开始的事件。 |
| `strategy` | `shift/merge/skip` | 移到其他日期、合并训练或跳过；写入草稿 `strategy`。 |
| `target_date` | shift/merge 必填 | 写入草稿 `target_date`。 |
| `reason` | 可空，最长 1000 | 调整原因。 |

草稿还保存 `before_events/after_events`、时长变化、训练量变化和警告。批准确认后，Service 会再次比较当前事件与草稿基准，防止陈旧方案覆盖新日历。

`calendar_events.content_snapshot` 保存当时训练内容；因此后来修改计划不会悄悄改变已安排事件。`actual_workout_id` 在训练完成后指向实际训练。

## 8. 实际训练 `/api/v1/workouts`

### 8.1 接口对应

| 接口 | Router -> Service/Repository | Schema/查询 | 表 |
|---|---|---|---|
| `POST /workouts` | `start_workout` -> `create_workout` | `WorkoutCreateRequest` + 幂等 | `workouts`、`workout_exercises`、读取/更新 `calendar_events`、`idempotency_records` |
| `GET /workouts/active` | `get_active_workout` -> `get_active` | 无 | `workouts`、`workout_exercises`、`workout_sets` |
| `GET /workouts` | `list_workouts` -> Repository | 日期、`status`、分页 | `workouts`、`workout_sets`、`personal_records` |
| `GET /workouts/{workout_id}` | `get_workout` -> `get_aggregate` | Path | `workouts`、`workout_exercises`、`workout_sets` |
| `POST /workouts/{workout_id}/sets` | `create_workout_set` -> `create_set` | `WorkoutSetCreateRequest` + 幂等 | `workout_sets`、`idempotency_records` |
| `PATCH /workouts/{workout_id}/sets/{set_id}` | `update_workout_set` -> `update_set` | `WorkoutSetUpdateRequest` | `workout_sets`、`workout_set_revisions` |
| `POST /workouts/{workout_id}/exercises/{item_id}/replace` | `replace_workout_exercise` -> `replace_exercise` | `WorkoutExerciseReplaceRequest` | `workout_exercises`、读取 `exercises` |
| `POST /workouts/{workout_id}/pause` | `pause_workout` -> `pause_workout` | `WorkoutPauseRequest` + 幂等 | `workouts`、`idempotency_records` |
| `POST /workouts/{workout_id}/resume` | `resume_workout` -> `resume_workout` | `WorkoutResumeRequest` + 幂等 | `workouts`、`idempotency_records` |
| `POST /workouts/{workout_id}/finish` | `finish_workout` -> `finish_workout` | `WorkoutFinishRequest` + 幂等 | `workouts`、`calendar_events`、`personal_records`、`idempotency_records` |
| `POST /workouts/{workout_id}/progression-drafts` | `create_progression_draft` -> `create_progression_draft` | `ProgressionDraftCreateRequest` + 幂等 | `workouts`、`workout_sets`、`progression_drafts`、`idempotency_records` |
| `POST /workouts/{workout_id}/progression-drafts/{draft_id}/submit` | `submit_progression_draft` -> `submit_progression` | `ExpectedVersionRequest` + 幂等 | `progression_drafts`、`confirmations`、`idempotency_records` |

### 8.2 开始训练

| 字段 | 校验 | 含义/表对应 |
|---|---|---|
| `calendar_event_id` | 可选 UUID | 来源日历事件，写 `workouts.calendar_event_id`。 |
| `plan_day_id` | 可选 UUID | 来源计划日，写 `workouts.plan_day_id`。 |
| `started_at` | 必须带时区 | `workouts.started_at`。 |
| `pre_check` | 可选对象 | 整体写 `workouts.pre_check` JSONB。 |
| `sleep_quality/energy` | 可空，1～5 | 训练前睡眠和精力。 |
| `pain` | 列表 | 训练前疼痛信息。 |
| `available_minutes` | 可空，1～300 | 当天可训练时间。 |

Service 从日历 `content_snapshot` 或活动计划创建 `workout_exercises`；`name_snapshot/target_snapshot` 保证历史训练不会被动作库和计划的后续修改污染。每个用户数据库约束只允许一个 `in_progress` 或 `paused` 训练。

### 8.3 训练与休息计时

- `workouts.paused_at` 保存当前暂停的起点，`total_paused_seconds` 保存已结束暂停的累计秒数。
- `WorkoutResponse.elapsed_seconds` 是排除暂停后的有效训练时长。
- `POST /pause` 和 `POST /resume` 支持客户端真实发生时间，便于离线队列稍后同步。
- `WorkoutResponse.rest_timer` 根据最近一组 `completed_at` 和动作快照中的
  `rest_seconds` 计算，用于 App 重启或回到前台后恢复倒计时。
- App 正常运行时在设备本地逐秒刷新，服务端不承担实时计时循环。

### 8.4 记录和修改一组

| 字段 | 校验 | 含义/表对应 |
|---|---|---|
| `client_generated_id` | UUID | iOS 本地生成的组编号；与 `workout_id` 组合唯一，防止离线重复上传。 |
| `workout_exercise_id` | UUID | 对应 `workout_exercises.id`。 |
| `set_index` | `>=1`，同动作唯一 | 第几组。 |
| `weight_kg` | `>=0`，三位小数 | 实际重量。 |
| `reps` | 0～1000 | 实际次数。 |
| `rir` | 可空，0～10 | 剩余次数。 |
| `rpe` | 可空，1～10，一位小数 | 主观用力程度。 |
| `tags` | `warmup/working/failure/drop` 列表 | 组标签，JSONB。 |
| `notes` | 可空，最长 1000 | 备注。 |
| `completed_at` | 必须带时区且不能早于训练开始 | 组完成时间。 |
| 更新时 `reason` | 1～1000 | 为什么修改；写入 `workout_set_revisions.reason`。 |
| 更新时 `expected_version` | `>=1` | 对照 `workout_sets.version`。 |

修改前后快照分别写入 `workout_set_revisions.old_values/new_values`，保留审计历史。

### 8.4 替换、结束和渐进

| Schema.字段 | 校验/意义 |
|---|---|
| `replacement_exercise_id` | 新动作 ID；必须对用户可见。 |
| `reason` | 替换原因，写入 `workout_exercises.replacement_history`。 |
| `expected_workout_version` | 对照 `workouts.version`。 |
| `ended_at` | 带时区且晚于开始时间。 |
| `overall_difficulty/fatigue` | 可空，1～5。 |
| `pain` | 训练后疼痛列表。 |
| `interruption_reason` | 可空，最长 1000；存在时训练可标记 `interrupted`。 |
| `WorkoutFinishRequest.expected_version` | 防止重复结束或覆盖状态。 |
| `ProgressionDraftCreateRequest.exercise_ids` | 可空；只为指定动作生成下一阶段建议。 |

结束训练会计算时长、训练量、计划完成度以及 `max_weight/max_reps` PR，并写 `personal_records`。渐进建议先写 `progression_drafts`，提交后创建 confirmation；批准后才生成新训练计划版本。

## 9. 食物和营养 `/api/v1/foods`、`/api/v1/nutrition`

### 9.1 接口对应

| 接口 | Router -> Service/Repository | Schema/查询 | 表 |
|---|---|---|---|
| `GET /foods/search` | `search_foods` -> Repository | `keyword/region/state/page/page_size` | `foods`、`food_versions` |
| `POST /foods` | `create_food` -> `create_food` | `FoodCreateRequest` + 幂等 | `foods`、`food_versions`、`idempotency_records` |
| `POST /nutrition/entries` | `create_nutrition_entry` -> `create_entry` | `NutritionEntryCreateRequest` + 幂等 | `food_versions`、`nutrition_entries`、`idempotency_records` |
| `GET /nutrition/entries` | `list_nutrition_entries` -> Repository | `date`、可选 `meal_type` | `nutrition_entries` |
| `PATCH /nutrition/entries/{entry_id}` | `update_nutrition_entry` -> `update_entry` | `NutritionEntryUpdateRequest` | `nutrition_entries`、`nutrition_entry_revisions` |
| `GET /nutrition/daily-summary` | `get_daily_summary` -> `daily_summary` | `date` | `nutrition_entries`、`nutrition_target_versions` |
| `POST /nutrition/target-drafts` | `create_nutrition_target_draft` -> `create_target_draft` | `NutritionTargetDraftRequest` + 幂等 | `nutrition_target_drafts`、`idempotency_records` |
| `POST /nutrition/target-drafts/{target_id}/submit` | `submit_nutrition_target_draft` -> `submit_target` | `ExpectedVersionRequest` + 幂等 | `nutrition_target_drafts`、`confirmations`、`idempotency_records` |

### 9.2 食物 Schema

| 字段 | 校验 | 表对应/含义 |
|---|---|---|
| `name` | 1～160 | `foods.name`。 |
| `brand` | 可空，最长 120 | `foods.brand`。 |
| `basis_amount_g` | `>0` | `food_versions.basis_amount_g`，营养值所基于的克数，通常 100g。 |
| `kcal` | `>=0` | 基准份量热量。 |
| `protein_g/carbs_g/fat_g` | `>=0` | 基准份量三大营养素。 |

`Food` 保存身份和归属；`FoodVersion` 保存可追踪版本的营养值。用户自建食物写 `owner_user_id`，来源/置信度由 Service 设置。

### 9.3 饮食记录 Schema

| 字段 | 校验 | 表对应/含义 |
|---|---|---|
| `meal_type` | `breakfast/lunch/dinner/snack/other` | `nutrition_entries.meal_type`。 |
| `eaten_at` | 必须带时区 | `nutrition_entries.eaten_at`。 |
| `items` | 至少一项 | 计算后完整快照写入 `nutrition_entries.items` JSONB。 |
| `is_flexible_meal` | 默认 false | 是否自由餐。 |
| `notes` | 可空，最长 2000 | `nutrition_entries.notes`。 |
| `NutritionItemInput.food_version_id` | 可空 UUID | 有值时读取指定 `food_versions`，按 `amount_g/basis_amount_g` 换算。 |
| `amount_g` | `>0` | 实际摄入克数。 |
| `name/basis_amount_g/kcal/protein_g/carbs_g/fat_g/source/confidence` | 自定义估算时全部必填且营养非负 | 没有食物版本时也能保存完整来源快照。 |

`nutrition_entries.totals` JSONB 保存该餐计算后的总热量、蛋白质、碳水和脂肪。更新请求允许修改上述餐食字段，并额外要求 `reason` 和 `expected_version`；旧值、新值和原因写入 `nutrition_entry_revisions`。

### 9.4 营养目标

| 字段 | 校验 | 含义 |
|---|---|---|
| `effective_from` | 日期 | 目标开始生效日。 |
| `kcal_min/kcal_max` | 非负，min <= max | 每日热量范围。 |
| `protein_min_g/protein_max_g` | 同上 | 每日蛋白质范围。 |
| `carbs_min_g/carbs_max_g` | 同上 | 每日碳水范围。 |
| `fat_min_g/fat_max_g` | 同上 | 每日脂肪范围。 |

草稿存 `nutrition_target_drafts`；提交创建 confirmation；批准后将完整范围写入 `nutrition_target_versions.values` JSONB。每日汇总返回 `target`、已摄入 `consumed`、四项剩余范围 `remaining` 和记录完整度。

## 10. 身体数据与进度 `/api/v1/body`、`/api/v1/progress`

### 10.1 接口对应

| 接口 | Router -> Service/Repository | Schema/查询 | 表 |
|---|---|---|---|
| `POST /body/measurements` | `create_body_measurement` -> `create_measurement` | `BodyMeasurementCreateRequest` + 幂等 | `body_measurements`、`idempotency_records` |
| `GET /body/measurements` | `list_body_measurements` -> Repository | 日期、分页 | `body_measurements` |
| `PATCH /body/measurements/{measurement_id}` | `update_body_measurement` -> `update_measurement` | `BodyMeasurementUpdateRequest` | `body_measurements`、`body_measurement_revisions` |
| `POST /body/body-fat/navy` | `calculate_navy_body_fat` -> `navy_body_fat` | `NavyBodyFatRequest`；`save=true` 时必须幂等 | 可选写 `body_fat_estimates`、`idempotency_records` |
| `GET /progress/overview` | `get_progress_overview` -> `overview` | `start_date/end_date` | `workouts`、`nutrition_entries`、`body_measurements`、`calendar_events` |
| `GET /progress/body-trend` | `get_body_trend` -> `body_trend` | `metric/start_date/end_date/window` | `body_measurements`、`body_fat_estimates` |
| `GET /progress/prs` | `list_personal_records` -> Repository | 可选 `exercise_id/record_type`、分页 | `personal_records` |

### 10.2 身体测量 Schema

| 字段 | 校验 | 表对应/含义 |
|---|---|---|
| `measured_at` | 必须带时区 | `body_measurements.measured_at`。 |
| `weight_kg` | 可空，`>0`、`<=500` | 体重。 |
| `waist_cm` | 可空，`>0`、`<=400` | 腰围。 |
| `neck_cm` | 可空，`>0`、`<=200` | 颈围。 |
| `hip_cm` | 可空，`>0`、`<=400` | 臀围。 |
| `body_fat_percent` | 可空，`>0`、`<=70` | 手动体脂率。 |
| `body_fat_method` | 与体脂率同时提供，1～30 字符 | 测量方法，例如秤、皮脂钳。 |
| `source` | 1～30 | 数据来源。 |
| `conditions` | 可空，最长 500 | 测量条件，如晨起空腹。 |
| `notes` | 可空，最长 2000 | 备注。 |

创建时体重、围度、体脂至少有一项。更新请求增加必填 `reason` 和 `expected_version`，修改前后值进入 `body_measurement_revisions`。

### 10.3 Navy 体脂和趋势参数

| 字段 | 校验/含义 |
|---|---|
| `sex` | `male/female`，决定公式。 |
| `height_cm/waist_cm/neck_cm` | 正数且在合理上限内。 |
| `hip_cm` | 女性必填。 |
| `save` | false 只计算；true 保存估算及输入快照。 |
| `metric` | `weight/waist/body_fat`。 |
| `window` | `raw/7d/14d`，原始值或按日平滑窗口。 |

## 11. 确认流程 `/api/v1/confirmations`

| 接口 | Router -> Service | Schema/查询 | 表 |
|---|---|---|---|
| `GET /confirmations` | `list_confirmations` -> `DatabaseConfirmationService.list` | 可选 `status`、分页 | `confirmations` |
| `POST /confirmations/{confirmation_id}/approve` | `approve_confirmation` -> `approve` -> `_execute` | `ConfirmationApproveRequest` + 幂等 | `confirmations`、目标业务表、`idempotency_records` |
| `POST /confirmations/{confirmation_id}/reject` | `reject_confirmation` -> `reject` | `ConfirmationRejectRequest` | `confirmations` |

| 字段 | 含义 |
|---|---|
| `operation_type` | 要执行的命令：`training_plan_activate`、`calendar_reschedule`、`nutrition_target_activate`、`training_progression_apply`。 |
| `before` | 修改前快照，可空。 |
| `after` | 待执行参数，例如草稿 ID、草稿版本和基准活动版本。 |
| `reason/impact` | 为什么建议改，以及会影响什么。 |
| `status` | `pending/succeeded/rejected/failed/expired`。 |
| `expires_at` | 超过此时间不能批准。 |
| `result` | 成功执行后返回的业务结果。 |
| `rejection_reason` | 用户拒绝原因。 |
| `expected_version` | 只能批准/拒绝自己看到的 pending 版本。 |

批准时 Repository 使用 `SELECT ... FOR UPDATE` 锁住确认单；`_execute` 使用同一个数据库事务执行真实业务。业务失败则整体回滚，避免“确认成功但只改了一半”。

## 12. 健康检查和 Agent 状态

| 接口 | 状态 | 表 |
|---|---|---|
| `GET /health` | 根健康检查，返回服务状态 | 无 |
| `GET /api/v1/health` | API v1 健康检查 | 无 |
| `POST /api/v1/agent/chat`、`POST /api/v1/agent/chat/stream` | 执行通用 Agent 工作流；支持会话、图片、分支、工具和 SSE | `agent_conversations`、`agent_messages`、`agent_runs`、`memories`、知识库表 |
| `POST /api/v1/agent/conversations`、`POST /api/v1/agent/conversations/{id}/messages` | 创建空会话并在指定会话中发送 SSE 消息 | `agent_conversations`、`agent_messages`、`agent_runs` |

模型或外部存储未配置时，相关接口返回明确的 503；普通结构化业务接口不依赖模型启动。

## 13. 数据库表总览与关系

| 领域 | 表 | 作用和关键关系 |
|---|---|---|
| 账号 | `users` | 用户主表，其他用户数据通常通过 `user_id -> users.id` 隔离。 |
| 账号 | `credentials` | 一对一密码/首次设密/锁定状态，主键也是 `user_id`。 |
| 账号 | `profiles` | 一对一个人档案，带乐观锁 `version`。 |
| 账号 | `refresh_sessions` | 一个用户多台设备的刷新令牌会话。 |
| 目标 | `user_goals` | 版本化目标；每个用户最多一个 active。 |
| 目标 | `user_constraints` | 当前器械、动作偏好、伤病、过敏和饮食限制 JSONB。 |
| 动作 | `exercises` | 官方或用户自定义动作；`owner_user_id` 区分归属，`deleted_at` 软删除。 |
| 动作 | `exercise_muscles` | 动作与主要/次要肌群多对多关系。 |
| 动作 | `exercise_aliases` | 搜索别名。 |
| 动作 | `exercise_substitutions` | 来源动作到替代动作的有向关系。 |
| 动作 | `exercise_media` | 动画/图片的对象存储元数据。 |
| 训练 | `training_templates` | 官方计划模板和不可变 `days` 快照。 |
| 训练 | `training_plan_drafts` | 可编辑草稿，提交后等待确认。 |
| 训练 | `training_plan_versions` | 已激活不可变版本；`plan_id` 串起历史。 |
| 日历 | `calendar_events` | 某天计划事件和内容快照，可关联实际 workout。 |
| 日历 | `calendar_reschedule_drafts` | shift/merge/skip 的修改前后方案。 |
| 训练记录 | `workouts` | 一次训练的总体状态、时间和主观反馈。 |
| 训练记录 | `workout_exercises` | 训练中的动作快照及替换历史。 |
| 训练记录 | `workout_sets` | 每组重量、次数、RIR/RPE 和版本。 |
| 训练记录 | `workout_set_revisions` | 组记录修改审计。 |
| 训练记录 | `progression_drafts` | 训练后的渐进建议草稿。 |
| 进度 | `personal_records` | 最大重量/次数等个人纪录，关联 workout 和 set。 |
| 营养 | `foods` | 食物身份、品牌、地区和用户归属。 |
| 营养 | `food_versions` | 每份基准重量及宏量营养版本。 |
| 营养 | `nutrition_entries` | 餐食项目和总计快照。 |
| 营养 | `nutrition_entry_revisions` | 餐食修改审计。 |
| 营养 | `nutrition_target_drafts` | 待确认的每日营养范围。 |
| 营养 | `nutrition_target_versions` | 已激活不可变目标版本。 |
| 身体 | `body_measurements` | 体重、围度、手动体脂和条件。 |
| 身体 | `body_measurement_revisions` | 身体数据修改审计。 |
| 身体 | `body_fat_estimates` | Navy 等估算结果、输入、范围和置信度。 |
| 通用 | `confirmations` | 高影响操作的待确认命令和执行结果。 |
| 通用 | `idempotency_records` | 写请求的请求哈希与稳定响应。 |

关系的核心不是“所有字段都拆成列”，而是：稳定、常查询的字段使用普通列；计划天、餐食项目、快照和历史变化等结构化整体使用 JSONB。

## 14. 核心类和函数索引

| 层 | 主要类/函数 | 参数意义 |
|---|---|---|
| Router | 各 `api/routes/*.py` 的接口函数 | `body` 是 Schema；`*_id` 是路径资源；`user/session` 是依赖；Query/Header 是协议参数。 |
| Service | `AccountService` | `username/password/token/device_name` 处理设密、登录、锁定和令牌轮换。 |
| Service | `ProfileService`、`GoalsService` | `user_id` 限定用户；`changes/data` 是业务输入；`expected_version` 防覆盖。 |
| Service | `ExercisesService` | 查询过滤、创建/修改/软删自定义动作，并同步肌群关系。 |
| Service | `TrainingService` | 创建、验证、提交和激活计划；创建/应用日历调整。 |
| Service | `WorkoutService` | 开始训练、记录组、替换动作、完成训练、生成/应用渐进方案。 |
| Service | `NutritionService` | 创建食物/餐食、计算总计、目标草稿/激活。 |
| Service | `BodyService` | 身体测量、Navy 体脂、综合进度和平滑趋势。 |
| Service | `DatabaseConfirmationService` | `approve/reject` 检查版本、过期和状态，`_execute` 分发命令。 |
| Service | `IdempotencyService` | `begin` 认领 key 或重放结果；`complete` 保存最终响应。 |
| Repository | `SqlAlchemy*Repository` | 第一个业务参数通常是 `user_id`；ID 后常有 `lock=True`，表示更新前加行锁。 |
| Model | `Base`、`IdMixin`、`TimestampMixin` | 为模型统一提供映射基类、UUID 主键和时间戳。 |

异常类如 `*NotFoundError`、`*ConflictError` 属于 Service 的业务语言；Router 将它们转换为 `404/409/422` 等 HTTP 错误。这样 Service 不需要依赖 HTTP，也更容易单元测试。

### 14.1 核心 Service 方法参数速查

这里列的是对业务开发有意义的公开方法；以下划线开头的响应组装、快照转换等私有 helper 不需要由 Router 直接调用。

| 类.方法 | 关键参数 | 参数用途 |
|---|---|---|
| `AccountService.precreate_user` | `username/display_name/is_admin` | 本地管理员预创建账号和档案。 |
| `setup_password` | `username/setup_token/new_password` | 验证首次设密令牌并保存密码哈希。 |
| `login` | `username/password/device_name` | 验证账号、累计失败次数、创建令牌会话。 |
| `refresh_tokens` | `refresh_token` | 验证并轮换刷新令牌。 |
| `ProfileService.update_profile` | `user_id/changes/expected_version` | 更新当前用户明确传入的档案字段。 |
| `GoalsService.update_goals_and_constraints` | `user_id/data/expected_version` | 原子创建新目标版本并更新当前约束。 |
| `get_goals_and_constraints` | `user_id` | 获取活动目标和约束。 |
| `ExercisesService.list_exercises` | `user_id/keyword/equipment/muscle/page/page_size` | 搜索官方动作和当前用户动作。 |
| `get_exercise_detail` | `user_id/exercise_id` | 获取动作、别名、肌群和替代动作。 |
| `create_custom_exercise` | `user_id/data` | 创建归属于当前用户的动作。 |
| `update_custom_exercise` | `user_id/exercise_id/data/expected_version` | 版本化修改动作及肌群关系。 |
| `delete_custom_exercise` | `user_id/exercise_id/expected_version` | 软删除自定义动作。 |
| `TrainingService.create_manual_draft` | `user_id/body` | 从嵌套 Schema 创建计划草稿。 |
| `create_from_template` | `user_id/template_id/name` | 将官方模板快照复制为用户草稿。 |
| `get_draft` | `user_id/draft_id` | 获取自己的草稿。 |
| `update_draft` | `user_id/draft_id/body` | 按 `body.expected_version` 修改草稿。 |
| `validate_draft` | `user_id/draft` | 检查动作可见性、时长和计划结构，返回错误/警告/周时长。 |
| `submit_draft` | `user_id/draft_id/expected_version` | 将草稿提交并创建激活确认单。 |
| `activate_draft` | `user_id/draft_id/draft_version/base_plan_version_id` | confirmation 批准后激活；最后一个参数防止活动计划已变化。 |
| `create_reschedule_draft` | `user_id/body` | 根据 missed event 和策略计算改期前后方案。 |
| `submit_reschedule` | `user_id/draft_id/expected_version` | 提交改期草稿并创建确认单。 |
| `apply_reschedule` | `user_id/draft_id/draft_version` | 批准后再次校验并修改日历。 |
| `WorkoutService.create_workout` | `user_id/body` | 从日历/计划快照开始训练。 |
| `get_aggregate/get_active` | `user_id` 加 `workout_id`（详情时） | 组合 workout、动作和组。 |
| `create_set/update_set` | `user_id/workout_id` 加 `set_id/body` | 新增或带审计修改训练组。 |
| `replace_exercise` | `user_id/workout_id/item_id/body` | 替换一次训练中的动作，不改动作库。 |
| `finish_workout` | `user_id/workout_id/body` | 结束训练并计算训练量、PR、疼痛和完成度。 |
| `create_progression_draft` | `user_id/workout_id/body` | 根据已完成训练生成渐进建议。 |
| `submit_progression` | `user_id/workout_id/draft_id/expected_version` | 提交渐进草稿并创建确认单。 |
| `apply_progression` | `user_id/draft_id/draft_version/base_plan_version_id` | 批准后基于当前计划生成新版本。 |
| `NutritionService.create_food` | `user_id/body` | 创建私有 Food 和第一个 FoodVersion。 |
| `create_entry/update_entry` | `user_id` 加 `entry_id/body` | 换算营养、保存餐食快照；更新时保存修订。 |
| `daily_summary` | `user_id/day` | 汇总当天餐食并与当日有效目标比较。 |
| `create_target_draft` | `user_id/body` | 创建每日营养范围草稿。 |
| `submit_target` | `user_id/target_id/expected_version` | 提交目标并创建确认单。 |
| `activate_target` | `user_id/target_id/draft_version/base_target_version_id` | 批准后生成不可变目标版本。 |
| `BodyService.create_measurement/update_measurement` | `user_id` 加 `measurement_id/body` | 创建或带审计修改身体数据。 |
| `navy_body_fat` | `user_id/body` | 按性别和围度计算；`body.save` 决定是否入库。 |
| `overview` | `user_id/start_date/end_date` | 汇总训练、营养和身体变化。 |
| `body_trend` | `user_id/metric/start_date/end_date/window` | 生成原始或平滑趋势。 |
| `DatabaseConfirmationService.list` | `user_id/status/page/page_size` | 分页获取确认单并处理过期项。 |
| `approve/reject` | `user_id/confirmation_id/expected_version`，拒绝另有 `reason` | 锁定确认单后批准执行或拒绝。 |
| `IdempotencyService.begin` | `user_id/idempotency_key/operation/payload` | 计算请求哈希、认领 key 或返回历史结果。 |
| `complete` | `decision/response_status/response_body` | 保存第一次成功请求的稳定响应。 |

### 14.2 当前不属于正式公开业务的类

| 类/Schema | 状态 |
|---|---|
| `ConfirmationService`、`ConfirmationDraft` | 早期内存版骨架；公开 `/confirmations` 使用数据库版 `DatabaseConfirmationService`。 |
| `ConfirmationCreate/ConfirmationDecisionRequest/ConfirmationResponse` | 配合早期内存版设计，当前没有注册对应公开创建/统一 decision 接口。 |
| `AdminUserCreateRequest/AdminUserCreateResponse` | 管理/CLI 场景的 Schema，当前没有公开注册接口。 |
| `AgentChatRequest/AgentChatResponse` | 兼容的单次 Agent 对话接口；完整实现另含持久化会话、Agent Run、工具调用、SSE、Memory、图片和 RAG。请求 `message` 为 1～8000 字符，`conversation_id` 可空 UUID。 |

## 15. 写新接口时的最小检查清单

1. 在 `schemas/<domain>.py` 定义请求和响应，先做类型、范围、组合校验。
2. 在 `db/models/<domain>.py` 定义需要长期保存的数据和数据库约束。
3. 用 Alembic migration 创建/修改真实表。
4. 在 `repositories/<domain>.py` 写带 `user_id` 的查询。
5. 在 `services/<domain>.py` 写业务规则、版本检查和审计。
6. 在 `api/routes/<domain>.py` 解析 HTTP、调用 Service、转换错误和响应。
7. 对重复创建风险使用 `Idempotency-Key`；对修改使用 `expected_version`。
8. 高影响操作先创建 confirmation，不直接执行。
9. 至少写 Schema、Service、Route 测试；涉及 PostgreSQL 特性时写数据库集成测试。
