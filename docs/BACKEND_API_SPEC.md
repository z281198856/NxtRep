# NxtRep 后端 API 接口文档

## 概述

本文档只描述 NxtRep 当前需要开发的基础后端接口，不包含 Agent、RAG、Memory、主动消息、图片分析、离线同步和数据导出。

## 基础 URL

```text
http://localhost:8000/api/v1
```

## 认证方式

除登录、刷新令牌和首次设置密码外，其余接口都需要请求头：

```text
Authorization: Bearer access_token
```

创建记录或执行确认时还需要幂等请求头：

```text
Idempotency-Key: 客户端生成的UUID
```

## 通用响应格式

成功时直接返回接口定义的业务对象，不再额外包装 `code`、`message` 和 `data`。HTTP 状态码表示请求结果，例如 `200` 表示成功、`201` 表示创建成功。

对象响应示例：

```json
{
  "id": "uuid",
  "status": "active"
}
```

列表接口统一返回：

```json
{
  "list": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "has_more": false
}
```

所有失败响应统一使用以下结构：

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid username or password"
  }
}
```

`error.code` 是供 iOS 程序判断错误类型的稳定业务码；`error.message` 用于展示或调试，不应作为客户端分支判断条件。只有存在额外信息时才返回可选的 `error.details`。

参数校验失败示例：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "type": "string_too_short",
        "loc": ["body", "password"],
        "msg": "String should have at least 1 character",
        "input": ""
      }
    ]
  }
}
```

常见 HTTP 状态码：`400` 请求错误、`401` 未认证、`403` 无权限、`404` 数据不存在、`409` 当前资源状态冲突、`422` 参数校验失败、`423` 账号锁定、`500` 服务器错误、`503` 服务未配置或暂不可用。

当前已定义的业务错误码：

| error.code | HTTP 状态 | 说明 |
|---|---:|---|
| AUTHENTICATION_REQUIRED | 401 | 缺少认证信息 |
| INVALID_ACCESS_TOKEN | 401 | Access Token 无效、被篡改、已过期或对应用户不存在 |
| INVALID_CREDENTIALS | 401 | 用户名或密码错误 |
| ACCOUNT_DISABLED | 403 | 账号已禁用 |
| PASSWORD_SETUP_REQUIRED | 409 | 账号尚未完成首次密码设置 |
| ACCOUNT_LOCKED | 423 | 账号暂时锁定 |
| INVALID_REFRESH_TOKEN | 401 | Refresh Token 无效、已撤销或已过期 |
| INVALID_SETUP_TOKEN | 400 | 首次设置密码令牌无效或过期 |
| AUTH_NOT_CONFIGURED | 503 | JWT 等认证配置缺失 |
| VALIDATION_ERROR | 422 | 请求参数校验失败，具体字段见 `details` |
| PROFILE_NOT_FOUND | 404 | 当前用户的个人档案不存在 |
| PROFILE_VERSION_CONFLICT | 409 | 个人档案已被其他请求修改，客户端需要重新获取 |
| CONFIRMATION_NOT_FOUND | 404 | 确认记录不存在 |
| AGENT_NOT_CONFIGURED | 503 | Agent 服务尚未配置 |
| NOT_FOUND | 404 | 路径或资源不存在的通用错误 |
| INTERNAL_SERVER_ERROR | 500 | 未处理的服务器内部错误 |

## 接口详情

### 一、账号与个人档案

#### 1. 用户登录

- **接口地址**：`POST /auth/login`
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 预创建账号名 |
| password | string | 是 | 用户密码 |
| device_name | string | 否 | 设备名称 |

- **请求示例**：

```json
{
  "username": "zengsiqi",
  "password": "example_password",
  "device_name": "iPhone"
}
```

- **响应示例**：

```json
{
  "access_token": "access_token",
  "refresh_token": "refresh_token",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "username": "zengsiqi",
    "password_setup_required": false
  }
}
```

#### 2. 刷新令牌

- **接口地址**：`POST /auth/refresh`
- **请求参数**：`refresh_token`，string，必填。

```json
{
  "refresh_token": "refresh_token"
}
```

- **响应示例**：与登录接口相同，返回新的 access token 和 refresh token。

#### 3. 首次设置密码

- **接口地址**：`POST /auth/password/setup`
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 预创建账号名 |
| setup_token | string | 是 | 管理员生成的一次性设置令牌 |
| new_password | string | 是 | 新密码，8～128 位 |

```json
{
  "username": "zengsiqi",
  "setup_token": "one_time_token",
  "new_password": "new_password"
}
```

- **响应示例**：与登录接口相同，设置成功后直接返回令牌。

#### 4. 获取个人档案

- **接口地址**：`GET /profile`
- **请求头**：需要认证。

- **响应示例**：

```json
{
  "display_name": "Zeng",
  "sex": "male",
  "birth_date": "2000-01-01",
  "height_cm": "175.00",
  "experience_level": "beginner",
  "weekly_training_days": 3,
  "session_duration_minutes": 60,
  "timezone": "Asia/Shanghai",
  "version": 1
}
```

#### 5. 更新个人档案

- **接口地址**：`PATCH /profile`
- **请求头**：需要认证。
- **请求参数**：以下字段均可选，但 `expected_version` 必填。

| 参数名 | 类型 | 说明 |
|---|---|---|
| display_name | string | 昵称 |
| sex | string | male、female、other、unspecified |
| birth_date | date | 出生日期 |
| height_cm | decimal string | 身高 cm |
| experience_level | string | beginner、intermediate、advanced |
| weekly_training_days | integer | 每周训练 0～7 天 |
| session_duration_minutes | integer | 单次训练时长 |
| expected_version | integer | 当前版本号 |

时区不作为用户手动编辑字段。数据库默认使用 `Asia/Shanghai`，后续由 iOS 读取系统时区并通过系统设置同步。

```json
{
  "weekly_training_days": 4,
  "session_duration_minutes": 75,
  "expected_version": 1
}
```

- **响应示例**：返回更新后的完整个人档案，`version` 增加 1。

#### 6. 设置目标与限制

- **接口地址**：`PUT /profile/goals-and-constraints`
- **请求头**：需要认证。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| goal_type | string | 是 | muscle_gain、fat_loss_retain、recomposition、maintain、strength |
| target_date | date | 否 | 目标日期 |
| target_weight_kg | decimal string | 否 | 目标体重 |
| equipment | string[] | 是 | 可用器械 |
| preferred_exercises | uuid[] | 否 | 偏好动作 |
| disliked_exercises | uuid[] | 否 | 不喜欢动作 |
| pain_or_injuries | object[] | 否 | 疼痛或既往伤病 |
| allergies | string[] | 否 | 过敏原 |
| dietary_preferences | string[] | 否 | 饮食偏好和忌口 |
| expected_version | integer | 更新时是 | 首次设置不传；更新时传上次响应的 version |

`pain_or_injuries` 对象：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| kind | string | 是 | current_pain、past_injury、movement_limitation |
| body_part | string | 是 | 身体部位，最长 100 字符 |
| severity | integer | 否 | 1～10 |
| notes | string | 否 | 补充说明，最长 500 字符 |

```json
{
  "goal_type": "muscle_gain",
  "target_date": "2027-02-01",
  "target_weight_kg": "72.500",
  "equipment": ["barbell", "dumbbell", "cable"],
  "preferred_exercises": [],
  "disliked_exercises": [],
  "pain_or_injuries": [
    {
      "kind": "current_pain",
      "body_part": "left_knee",
      "severity": 3,
      "notes": "深蹲到底时不适"
    }
  ],
  "allergies": ["peanut"],
  "dietary_preferences": [],
  "expected_version": 1
}
```

首次设置时省略 `expected_version`。器械代码会转为小写，所有列表不允许重复；同一动作不能同时出现在偏好和不喜欢列表中。

- **响应示例**：

```json
{
  "version": 2,
  "goal": {
    "id": "uuid",
    "goal_type": "muscle_gain",
    "target_date": "2027-02-01",
    "target_weight_kg": "72.500",
    "status": "active"
  },
  "constraints": {
    "equipment": ["barbell", "dumbbell", "cable"],
    "preferred_exercises": [],
    "disliked_exercises": [],
    "pain_or_injuries": [
      {
        "kind": "current_pain",
        "body_part": "left_knee",
        "severity": 3,
        "notes": "深蹲到底时不适"
      }
    ],
    "allergies": ["peanut"],
    "dietary_preferences": []
  },
  "warnings": []
}
```

- **特殊错误**：`409 GOALS_VERSION_CONFLICT`，表示数据已被其他设备更新，客户端应重新获取后再提交。

### 二、动作库

#### 1. 获取动作列表

- **接口地址**：`GET /exercises`
- **请求头**：需要认证。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 搜索名称或别名 |
| equipment | string | 否 | 按器械筛选 |
| muscle | string | 否 | 按肌群筛选 |
| page | integer | 否 | 默认 1 |
| page_size | integer | 否 | 默认 20，最大 100 |

```text
GET /exercises?keyword=深蹲&page=1&page_size=20
```

- **响应示例**：

```json
{
  "list": [
    {
      "id": "uuid",
      "name_zh": "杠铃深蹲",
      "aliases": [
        "深蹲"
      ],
      "equipment": "barbell",
      "primary_muscles": [
        "quadriceps",
        "gluteus"
      ],
      "is_custom": false
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_more": false
}
```

#### 2. 获取动作详情

- **接口地址**：`GET /exercises/{exercise_id}`
- **路径参数**：`exercise_id`，uuid，必填。

- **响应示例**：

```json
{
  "id": "uuid",
  "name_zh": "杠铃深蹲",
  "movement_pattern": "squat",
  "equipment": "barbell",
  "primary_muscles": [
    "quadriceps",
    "gluteus"
  ],
  "secondary_muscles": [
    "hamstring"
  ],
  "instructions": [
    "站稳并收紧核心",
    "屈髋屈膝下蹲",
    "脚掌发力站起"
  ],
  "common_errors": [
    "膝盖内扣"
  ],
  "safety_notes": [
    "出现疼痛时停止动作"
  ],
  "substitutions": []
}
```

#### 3. 创建自定义动作

- **接口地址**：`POST /exercises`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name_zh | string | 是 | 动作名称 |
| equipment | string | 是 | 器械 |
| primary_muscles | string[] | 是 | 主要肌群 |
| secondary_muscles | string[] | 否 | 次要肌群 |
| notes | string | 否 | 个人备注 |

```json
{
  "name_zh": "高脚杯深蹲",
  "equipment": "dumbbell",
  "primary_muscles": ["quadriceps", "gluteus"],
  "notes": "家里训练使用"
}
```

- **响应示例**：返回创建后的动作详情，HTTP 状态码为 201。

#### 4. 更新自定义动作

- **接口地址**：`PATCH /exercises/{exercise_id}`
- **请求参数**：创建接口字段均可选，另有必填 `expected_version`。
- **响应示例**：返回更新后的动作详情。

#### 5. 删除自定义动作

- **接口地址**：`DELETE /exercises/{exercise_id}`
- **查询参数**：`expected_version`，integer，必填。
- **响应示例**：

```json
null
```

### 三、训练计划

#### 1. 获取官方模板列表

- **接口地址**：`GET /training/templates`
- **请求参数**：`goal_type`、`days_per_week`、`equipment` 均可选。

- **响应示例**：

```json
[
  {
    "id": "uuid",
    "name": "三天全身训练",
    "goal_types": [
      "muscle_gain",
      "strength"
    ],
    "days_per_week": 3,
    "duration_minutes": 60
  }
]
```

#### 2. 创建手动计划草稿

- **接口地址**：`POST /training/plan-drafts`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 计划名称 |
| weekly_frequency | integer | 是 | 每周训练次数 |
| days | object[] | 是 | 训练日列表 |

`days` 中的动作字段：`exercise_id`、`order_no`、`target_sets`、`rep_min`、`rep_max`、`target_load_kg`（可选）、`target_rir`（可选）、`rest_seconds`（可选）。

```json
{
  "name": "三天全身训练",
  "weekly_frequency": 3,
  "days": [
    {
      "day_index": 1,
      "name": "训练A",
      "estimated_minutes": 60,
      "exercises": [
        {
          "exercise_id": "uuid",
          "order_no": 1,
          "target_sets": 5,
          "rep_min": 5,
          "rep_max": 5,
          "target_load_kg": "60.000",
          "target_rir": 2,
          "rest_seconds": 180
        }
      ]
    }
  ]
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "name": "三天全身训练",
  "status": "editing",
  "version": 1,
  "days": []
}
```

#### 3. 从模板创建计划草稿

- **接口地址**：`POST /training/plan-drafts/from-template`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：`template_id` 必填，`name` 可选。

```json
{
  "template_id": "uuid",
  "name": "我的三天训练"
}
```

- **响应示例**：返回完整计划草稿，HTTP 状态码为 201。

#### 4. 获取计划草稿

- **接口地址**：`GET /training/plan-drafts/{draft_id}`
- **路径参数**：`draft_id`，uuid，必填。
- **响应示例**：返回计划名称、训练日、动作、校验结果、状态和版本。

#### 5. 更新计划草稿

- **接口地址**：`PATCH /training/plan-drafts/{draft_id}`
- **请求参数**：`name`、`weekly_frequency`、`days` 均可选，`expected_version` 必填。
- **响应示例**：返回更新后的完整草稿。

#### 6. 校验计划草稿

- **接口地址**：`POST /training/plan-drafts/{draft_id}/validate`
- **请求参数**：`expected_version`，integer，必填。

- **响应示例**：

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "estimated_weekly_minutes": 180
}
```

#### 7. 提交并激活计划草稿

- **接口地址**：`POST /training/plan-drafts/{draft_id}/submit`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：`expected_version`，integer，必填。
- **说明**：提交后生成确认记录，批准前不会激活计划。

- **响应示例**：

```json
{
  "confirmation_id": "uuid",
  "operation_type": "training_plan_activate",
  "status": "pending",
  "before": null,
  "after": {
    "plan_draft_id": "uuid"
  },
  "impact": "确认后将作为当前训练计划"
}
```

#### 8. 获取当前训练计划

- **接口地址**：`GET /training/plans/active`
- **响应示例**：返回当前计划 ID、版本号、训练日和完整动作目标。

#### 9. 获取计划版本历史

- **接口地址**：`GET /training/plans/{plan_id}/versions`
- **请求参数**：`page`、`page_size` 可选。
- **响应示例**：返回版本列表；历史版本只读。

### 四、训练日历

#### 1. 获取训练日历

- **接口地址**：`GET /calendar`
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| start_date | date | 是 | 开始日期 |
| end_date | date | 是 | 结束日期 |

```text
GET /calendar?start_date=2026-08-01&end_date=2026-09-01
```

- **响应示例**：

```json
[
  {
    "id": "uuid",
    "scheduled_date": "2026-08-22",
    "status": "planned",
    "plan_day_id": "uuid",
    "title": "训练A",
    "estimated_minutes": 60,
    "actual_workout_id": null
  }
]
```

#### 2. 创建漏练调整草稿

- **接口地址**：`POST /calendar/reschedule-drafts`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| missed_event_id | uuid | 是 | 漏练日历事件 |
| strategy | string | 是 | shift、merge 或 skip |
| target_date | date | 否 | 顺延或合并的目标日期 |
| reason | string | 否 | 漏练原因 |

```json
{
  "missed_event_id": "uuid",
  "strategy": "shift",
  "target_date": "2026-08-24",
  "reason": "临时加班"
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "strategy": "shift",
  "before_events": [],
  "after_events": [],
  "duration_change_minutes": 0,
  "volume_change_percent": "0.00",
  "warnings": [],
  "version": 1
}
```

#### 3. 提交日历调整草稿

- **接口地址**：`POST /calendar/reschedule-drafts/{draft_id}/submit`
- **请求头**：需要 Idempotency-Key。
- **请求参数**：`expected_version`，integer，必填。
- **响应示例**：返回待批准的确认记录。

### 五、训练执行与记录

#### 1. 开始训练

- **接口地址**：`POST /workouts`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| calendar_event_id | uuid | 否 | 对应日历事件 |
| plan_day_id | uuid | 否 | 对应计划训练日 |
| started_at | datetime | 是 | 开始时间 |
| pre_check | object | 否 | 睡眠、精力、疼痛和可用时间 |

```json
{
  "calendar_event_id": "uuid",
  "started_at": "2026-08-22T10:00:00+08:00",
  "pre_check": {
    "sleep_quality": 4,
    "energy": 4,
    "pain": [],
    "available_minutes": 60
  }
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "status": "in_progress",
  "started_at": "2026-08-22T10:00:00+08:00",
  "version": 1,
  "exercises": [
    {
      "id": "uuid",
      "exercise_id": "uuid",
      "name_snapshot": "杠铃深蹲",
      "target_snapshot": {
        "sets": 5,
        "rep_min": 5,
        "rep_max": 5
      },
      "sets": []
    }
  ]
}
```

#### 2. 获取未结束训练

- **接口地址**：`GET /workouts/active`
- **响应示例**：返回未结束训练及全部已保存组；没有时返回 404。

#### 3. 获取训练历史

- **接口地址**：`GET /workouts`
- **请求参数**：`start_date`、`end_date`、`status`、`page`、`page_size` 均可选。
- **响应示例**：返回分页训练摘要，包括日期、时长、完成组数、训练量和 PR 数量。

#### 4. 获取训练详情

- **接口地址**：`GET /workouts/{workout_id}`
- **路径参数**：`workout_id`，uuid，必填。
- **响应示例**：返回训练快照、所有动作、组记录和训练反馈。

#### 5. 记录一组训练

- **接口地址**：`POST /workouts/{workout_id}/sets`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| client_generated_id | uuid | 是 | Flutter 本地生成，用于防重复 |
| workout_exercise_id | uuid | 是 | 本次训练中的动作 ID |
| set_index | integer | 是 | 第几组 |
| weight_kg | decimal string | 是 | 重量 kg |
| reps | integer | 是 | 次数 |
| rir | integer | 否 | 0～10 |
| rpe | decimal string | 否 | 1～10 |
| tags | string[] | 否 | warmup、working、failure、drop |
| notes | string | 否 | 单组备注 |
| completed_at | datetime | 是 | 完成时间 |

```json
{
  "client_generated_id": "uuid",
  "workout_exercise_id": "uuid",
  "set_index": 1,
  "weight_kg": "60.000",
  "reps": 5,
  "rir": 2,
  "tags": ["working"],
  "completed_at": "2026-08-22T10:15:00+08:00"
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "set_index": 1,
  "weight_kg": "60.000",
  "reps": 5,
  "rir": 2,
  "version": 1
}
```

#### 6. 修改一组训练

- **接口地址**：`PATCH /workouts/{workout_id}/sets/{set_id}`
- **请求参数**：重量、次数、RIR、RPE、标签和备注均可选；`reason`、`expected_version` 必填。

```json
{
  "weight_kg": "62.500",
  "reason": "刚才输错重量",
  "expected_version": 1
}
```

- **响应示例**：返回修改后的组记录；服务器保留修改历史。

#### 7. 替换训练动作

- **接口地址**：`POST /workouts/{workout_id}/exercises/{item_id}/replace`
- **请求参数**：`replacement_exercise_id`、`reason`、`expected_workout_version` 均必填。
- **响应示例**：返回替换后的完整训练内容，并保留原动作快照。

#### 8. 完成训练

- **接口地址**：`POST /workouts/{workout_id}/finish`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| ended_at | datetime | 是 | 结束时间 |
| overall_difficulty | integer | 否 | 总体难度 1～5 |
| fatigue | integer | 否 | 疲劳 1～5 |
| pain | object[] | 否 | 疼痛位置、程度和说明 |
| interruption_reason | string | 否 | 中断原因 |
| expected_version | integer | 是 | 训练版本 |

```json
{
  "ended_at": "2026-08-22T11:05:00+08:00",
  "overall_difficulty": 4,
  "fatigue": 3,
  "pain": [],
  "expected_version": 8
}
```

- **响应示例**：

```json
{
  "workout_id": "uuid",
  "duration_seconds": 3900,
  "completed_sets": 15,
  "total_volume_kg": "6850.000",
  "prs": [],
  "pain_flags": [],
  "plan_adherence": "0.93"
}
```

#### 9. 获取下次进阶建议草稿

- **接口地址**：`POST /workouts/{workout_id}/progression-drafts`
- **请求头**：需要 Idempotency-Key。
- **请求参数**：`exercise_ids`，uuid[]，可选；不传则分析全部动作。

- **响应示例**：

```json
{
  "id": "uuid",
  "suggestions": [
    {
      "exercise_id": "uuid",
      "current_target": {
        "weight_kg": "60.000",
        "reps": 5
      },
      "proposed_target": {
        "weight_kg": "62.500",
        "reps": 5
      },
      "evidence": [
        "最近两次完成全部目标组",
        "最近一次RIR为2"
      ],
      "warnings": []
    }
  ],
  "version": 1
}
```

#### 10. 提交进阶建议草稿

- **接口地址**：`POST /workouts/{workout_id}/progression-drafts/{draft_id}/submit`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：`expected_version`，integer，必填。
- **响应示例**：返回待批准的确认记录；批准后生成新计划版本，不修改历史训练。

### 六、饮食记录

#### 1. 搜索食物

- **接口地址**：`GET /foods/search`
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 是 | 食物名称或品牌 |
| region | string | 否 | 地区 |
| state | string | 否 | raw、cooked 等状态 |
| page | integer | 否 | 默认 1 |
| page_size | integer | 否 | 默认 20 |

```text
GET /foods/search?keyword=鸡胸肉&state=cooked
```

- **响应示例**：

```json
{
  "list": [
    {
      "id": "uuid",
      "food_version_id": "uuid",
      "name": "熟鸡胸肉",
      "state": "cooked",
      "basis_amount_g": "100.000",
      "kcal": "165.00",
      "protein_g": "31.000",
      "carbs_g": "0.000",
      "fat_g": "3.600",
      "source": "USDA",
      "confidence": "high"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_more": false
}
```

#### 2. 创建自定义食物

- **接口地址**：`POST /foods`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 食物名称 |
| brand | string | 否 | 品牌 |
| basis_amount_g | decimal string | 是 | 营养基准重量 |
| kcal | decimal string | 是 | 热量 |
| protein_g | decimal string | 是 | 蛋白质 |
| carbs_g | decimal string | 是 | 碳水 |
| fat_g | decimal string | 是 | 脂肪 |

```json
{
  "name": "自制鸡肉饭",
  "basis_amount_g": "300.000",
  "kcal": "520.00",
  "protein_g": "42.000",
  "carbs_g": "58.000",
  "fat_g": "12.000"
}
```

- **响应示例**：返回新建食物详情、来源 `user_confirmed` 和版本 ID。

#### 3. 创建饮食记录

- **接口地址**：`POST /nutrition/entries`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| meal_type | string | 是 | breakfast、lunch、dinner、snack、other |
| eaten_at | datetime | 是 | 食用时间 |
| items | object[] | 是 | 食物项目 |
| is_flexible_meal | boolean | 否 | 是否自由餐，默认 false |
| notes | string | 否 | 备注 |

每个 item：`food_version_id`、`amount_g` 必填；自定义估算时可提交 `name`、营养值、来源和可信度。

```json
{
  "meal_type": "lunch",
  "eaten_at": "2026-08-22T12:30:00+08:00",
  "items": [
    {
      "food_version_id": "uuid",
      "amount_g": "200.000"
    }
  ],
  "is_flexible_meal": false
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "meal_type": "lunch",
  "eaten_at": "2026-08-22T12:30:00+08:00",
  "items": [],
  "totals": {
    "kcal": "330.00",
    "protein_g": "62.000",
    "carbs_g": "0.000",
    "fat_g": "7.200"
  },
  "version": 1
}
```

#### 4. 获取某日饮食记录

- **接口地址**：`GET /nutrition/entries`
- **请求参数**：`date` 必填，`meal_type` 可选。

```text
GET /nutrition/entries?date=2026-08-22
```

- **响应示例**：返回该日全部餐次和食物营养快照。

#### 5. 修改饮食记录

- **接口地址**：`PATCH /nutrition/entries/{entry_id}`
- **请求参数**：餐次、时间、items、自由餐和备注均可选；`reason`、`expected_version` 必填。
- **响应示例**：返回修改后的记录，历史营养快照和修改记录保留。

#### 6. 获取每日营养汇总

- **接口地址**：`GET /nutrition/daily-summary`
- **请求参数**：`date`，date，必填。

- **响应示例**：

```json
{
  "date": "2026-08-22",
  "target": {
    "kcal_min": "2200.00",
    "kcal_max": "2400.00",
    "protein_min_g": "140.000",
    "protein_max_g": "160.000"
  },
  "consumed": {
    "kcal": "1650.00",
    "protein_g": "112.000",
    "carbs_g": "170.000",
    "fat_g": "55.000"
  },
  "remaining": {
    "kcal_min": "550.00",
    "kcal_max": "750.00",
    "protein_min_g": "28.000",
    "protein_max_g": "48.000",
    "carbs_min_g": "50.000",
    "carbs_max_g": "110.000",
    "fat_min_g": "0.000",
    "fat_max_g": "20.000"
  },
  "record_completeness": "0.85"
}
```

#### 7. 设置营养目标

- **接口地址**：`POST /nutrition/target-drafts`
- **请求头**：需要 Idempotency-Key。
- **请求参数**：`effective_from`、热量上下限、蛋白质/碳水/脂肪上下限均必填。

```json
{
  "effective_from": "2026-08-25",
  "kcal_min": "2200.00",
  "kcal_max": "2400.00",
  "protein_min_g": "140.000",
  "protein_max_g": "160.000",
  "carbs_min_g": "220.000",
  "carbs_max_g": "280.000",
  "fat_min_g": "55.000",
  "fat_max_g": "75.000"
}
```

- **响应示例**：返回营养目标草稿及版本。调用 `POST /nutrition/target-drafts/{id}/submit` 后生成确认记录。

#### 8. 提交营养目标草稿

- **接口地址**：`POST /nutrition/target-drafts/{target_id}/submit`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：`expected_version`，integer，必填。
- **响应示例**：返回待批准的确认记录；批准后新目标生效，旧目标进入历史版本。

### 七、身体数据与进展

#### 1. 记录身体数据

- **接口地址**：`POST /body/measurements`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| measured_at | datetime | 是 | 测量时间 |
| weight_kg | decimal string | 否 | 体重 |
| waist_cm | decimal string | 否 | 腰围 |
| neck_cm | decimal string | 否 | 颈围 |
| hip_cm | decimal string | 否 | 臀围 |
| body_fat_percent | decimal string | 否 | 用户从体脂秤、DEXA 等其他来源录入的体脂率 |
| body_fat_method | string | 录入体脂时必填 | 体脂来源或测量方法 |
| source | string | 是 | manual、scale 等来源 |
| conditions | string | 否 | 测量条件 |
| notes | string | 否 | 备注 |

体重、一个围度或体脂率至少填写一项。手工录入体脂时，`body_fat_percent` 和
`body_fat_method` 必须同时提交；不同来源的体脂值仅用于分别观察趋势。

```json
{
  "measured_at": "2026-08-22T07:30:00+08:00",
  "weight_kg": "72.300",
  "waist_cm": "81.50",
  "neck_cm": "37.00",
  "source": "manual",
  "conditions": "起床后空腹"
}
```

- **响应示例**：返回记录 ID、全部测量值、日期和版本。

#### 2. 获取身体数据

- **接口地址**：`GET /body/measurements`
- **请求参数**：`start_date`、`end_date`、`page`、`page_size` 均可选。
- **响应示例**：返回分页原始测量记录。

#### 3. 修改身体数据

- **接口地址**：`PATCH /body/measurements/{measurement_id}`
- **请求参数**：测量字段均可选，`reason`、`expected_version` 必填。
- **响应示例**：返回修改后的记录并保留修改历史。

#### 4. 美军围度法体脂估算

- **接口地址**：`POST /body/body-fat/navy`
- **请求头**：`save=true` 时需要认证、Idempotency-Key；仅计算不保存时不要求幂等键。
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| sex | string | 是 | male 或 female |
| height_cm | decimal string | 是 | 身高 |
| waist_cm | decimal string | 是 | 腰围 |
| neck_cm | decimal string | 是 | 颈围 |
| hip_cm | decimal string | 女性必填 | 臀围 |
| save | boolean | 否 | 是否保存结果 |

- **响应示例**：

```json
{
  "method": "navy",
  "value_percent": "16.80",
  "range_min_percent": "13.80",
  "range_max_percent": "19.80",
  "confidence": "medium",
  "disclaimer": "结果仅用于观察趋势，不是医学测量"
}
```

#### 5. 获取进展概览

- **接口地址**：`GET /progress/overview`
- **请求参数**：`start_date`、`end_date` 必填。

- **响应示例**：

```json
{
  "training": {
    "workout_count": 10,
    "completion_rate": "0.83",
    "total_duration_minutes": 620,
    "pr_count": 3
  },
  "nutrition": {
    "average_kcal": "2280.00",
    "record_completeness": "0.81"
  },
  "body": {
    "weight_start_kg": "73.20",
    "weight_end_kg": "72.30",
    "smoothed_change_kg": "-0.65"
  }
}
```

#### 6. 获取身体趋势

- **接口地址**：`GET /progress/body-trend`
- **请求参数**：`metric`（weight、waist、body_fat）、`start_date`、`end_date`、`window`（raw、7d、14d）。
- **响应示例**：返回日期、原始值和平滑值数组。

#### 7. 获取个人纪录

- **接口地址**：`GET /progress/prs`
- **请求参数**：`exercise_id`、`record_type`、`page`、`page_size` 均可选。
- **响应示例**：返回 PR、动作变式、数值、发生时间以及 workout_id、set_id。

### 八、确认操作

#### 1. 获取待确认列表

- **接口地址**：`GET /confirmations`
- **请求参数**：`status`、`page`、`page_size` 可选。

- **响应示例**：

```json
{
  "list": [
    {
      "id": "uuid",
      "operation_type": "training_plan_activate",
      "before": null,
      "after": {
        "plan_draft_id": "uuid"
      },
      "reason": "用户提交新的训练计划",
      "impact": "未来日历使用新计划，历史训练不变",
      "status": "pending",
      "version": 1,
      "expires_at": "2026-08-23T10:00:00+08:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_more": false
}
```

#### 2. 批准确认操作

- **接口地址**：`POST /confirmations/{confirmation_id}/approve`
- **请求头**：需要认证、Idempotency-Key。
- **请求参数**：`expected_version`，integer，必填。

```json
{
  "expected_version": 1
}
```

- **响应示例**：

```json
{
  "id": "uuid",
  "status": "succeeded",
  "result": {
    "resource_id": "uuid",
    "resource_version": 1
  },
  "executed_at": "2026-08-22T10:05:00+08:00"
}
```

资源在确认前已经变化时返回 409，客户端需要刷新并重新创建草稿。

#### 3. 拒绝确认操作

- **接口地址**：`POST /confirmations/{confirmation_id}/reject`
- **请求参数**：`expected_version` 必填，`reason` 可选。

```json
{
  "expected_version": 1,
  "reason": "暂时不想修改"
}
```

- **响应示例**：返回 `status: rejected` 的确认记录，业务数据保持不变。
