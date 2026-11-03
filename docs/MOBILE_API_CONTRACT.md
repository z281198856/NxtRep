# NxtRep 移动端 API 契约

本文固定移动端与后端之间最容易出错的五项约定。可交互字段和状态码以运行中的
`/openapi.json` 为唯一机器可读来源；本文说明客户端实现规则。

## 1. 响应格式

- 普通成功响应直接返回 OpenAPI 中声明的强类型对象，不额外套 `data`。
- 分页列表通常返回 `list/total/page/page_size/has_more`；游标接口使用各自明确声明的
  `next_cursor` 或 `next_sequence`。
- 成功且无需返回内容的操作统一返回 `204 No Content`，客户端不要解析 JSON。
- 文件下载按接口声明的媒体类型处理；JSON 导出返回带
  `Content-Disposition: attachment` 的 JSON 对象。
- Agent 流式接口返回 `text/event-stream`，不属于普通 JSON 响应。

所有非流式 HTTP 错误统一为：

```json
{
  "error": {
    "code": "EXERCISE_VERSION_CONFLICT",
    "message": "Exercise has been modified",
    "details": {}
  }
}
```

`details` 可省略。移动端逻辑判断使用稳定的 `error.code`，不要匹配 `message` 文案。

## 2. JWT 与移动端会话

登录、首次设密、修改密码和刷新接口都返回：

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_expires_in": 2592000,
  "user": {}
}
```

- `access_token` 是短期 JWT，用 `Authorization: Bearer <access_token>` 发送。
- `refresh_token` 是一次性轮换的不透明随机令牌，服务端只保存哈希；每次刷新成功后必须
  原子替换本地旧值。
- 令牌响应带 `Cache-Control: no-store` 和 `Pragma: no-cache`。
- `refresh_token` 存入 iOS Keychain 或 Android Keystore；访问令牌优先只保存在内存中。
- 客户端必须把并发刷新合并成一个请求。收到业务接口 `401` 后最多刷新一次、重放原请求
  一次；刷新仍失败就回到登录页，禁止无限重试。
- 不得在日志、崩溃报告、埋点或 URL Query 中记录任何令牌。

用户可通过 `GET /api/v1/auth/sessions` 查看设备会话，并通过
`DELETE /api/v1/auth/sessions/{session_id}` 撤销指定设备。

设备列表中的 `is_current` 由服务端依据当前访问凭证标记，客户端不能按设备名称推测。
`POST /api/v1/auth/sessions/revoke-others` 保留当前登录并撤销其他登录。
访问凭证绑定会话，撤销后旧访问凭证及续期请求都会被拒绝；轮换刷新令牌保留同一会话 ID
和首次登录时间。升级前未绑定会话的旧访问凭证返回 `INVALID_ACCESS_TOKEN`，客户端使用
仍有效的刷新令牌完成一次升级，不继续放行无法关联设备的访问。

修改密码需提交当前密码，新密码为 8–128 个字符且不能与原密码相同。成功时撤销旧登录并
返回当前设备的新令牌对。当前密码错误返回 `INVALID_CURRENT_PASSWORD`，不能把它当作
访问令牌过期而自动刷新、重放密码请求；连续五次错误会临时锁定 15 分钟。密码修改与刷新
需要串行更新本机令牌。网络中断或响应无法确认时不自动重复修改，应重新登录核对结果。

## 3. 手机图片上传

移动端先请求 `GET /api/v1/media/images/capabilities`，读取当前允许的格式、大小、像素、
边长和上传地址有效期。标准流程为：

1. 相机或相册得到图片后读取真实格式和字节数。
2. HEIC/HEIF 按能力响应中的 `convert_before_upload` 在本机转为 JPEG，并修正方向；不要只改
   文件扩展名。
3. 图片超过 `max_bytes/max_pixels/max_dimension` 时在本机等比缩放和压缩。
4. 调用 `POST /api/v1/media/images/upload-intents`。
5. 使用返回的 HTTPS `upload_url`、`method` 和全部 `headers` 将字节直接 PUT 到对象存储，
   不把大图传给 API 服务器。
6. PUT 成功后调用 `POST /api/v1/media/images/{asset_id}/complete`，传入实际格式和字节数。
7. 只有完成接口返回 `status=ready` 后，才能把 `asset_id` 用于照片分析或 Agent。

后端会重新下载、解码、校正 EXIF 方向、清除元数据、重新编码，并验证格式、长度、尺寸和
图片归属。上传 URL 是短期私有签名地址，不能持久化或分享。移动网络下若 PUT 结果不明确，
可先调用完成接口确认；若对象不存在，再申请新的上传意图。

## 4. 数据库边界

移动端只允许访问 HTTPS API 和后端签发的短期对象存储上传 URL，绝不能连接 PostgreSQL。
前端工程中不得出现数据库连接串、数据库账号、SQL、ORM 模型或云数据库公网密钥。

`user_id` 由后端根据访问令牌绑定，客户端不能替其他用户指定；Repository 查询同时使用
`user_id` 和资源 ID。生产部署时数据库应放在私网或安全组内，只允许后端运行环境访问。

### 个人资料与草稿

个人资料补充约定：`GET/PATCH /api/v1/profile` 返回 `weight_kg` 和
`weight_recorded_at`，来源是当前用户最近一条未删除、非未来的体重记录，不另存一份静态体重。
`PATCH /profile` 可选传入 `weight_kg`，与其他资料在同一事务内保存，并使用
`expected_version` 防止重复提交。新体重追加到身体测量历史；不传或传 `null` 不删除历史。
客户端只在体重改变时发送该字段，避免只编辑昵称也重复记录体重。

训练与饮食目标草稿会先读取当前账号资料和最近身体记录；缺少非关键个性化信息不要求
补完整问卷，可以生成说明暂定假设的草稿。`nutrition_target_draft` 是每日目标任务，
与需要餐次、食物等信息的 `nutrition_record_draft` 分开；二者均须用户确认才生效。

## 5. Agent 流式响应

以下两个 `POST` 接口支持 SSE：

- `/api/v1/agent/chat/stream`
- `/api/v1/agent/conversations/{conversation_id}/messages`

响应头包含 `Content-Type: text/event-stream`、`Cache-Control: no-cache, no-transform` 和
`X-Accel-Buffering: no`。事件包含 `event`、JSON `data`，有序增量还包含 SSE `id`：

```text
id: 1
event: message_delta
data: {"event":"message_delta","delta":"你好","sequence":1}

```

服务端会发送 `: heartbeat` 保活。移动端应使用支持 **POST 响应流** 的 HTTP 客户端逐行解析，
不能依赖只支持 GET 的浏览器 `EventSource`。`granularity=chunk` 更省电省流量，
`granularity=character` 适合逐字动画。收到 `completed`、`cancelled` 或 `failed` 即结束；断线后
查询会话消息和 run 状态，不要把半截文本当成完整答案。

## 6. 历史对话草稿恢复

`GET /api/v1/agent/conversations/{conversation_id}/confirmations` 返回当前账户、当前会话的
`confirmation_cards` 和 `resolved_counts`。前者仅包含仍有效的待确认卡，带当前版本、
命令内容及可选的 `draft` 审核预览；后者统计 `succeeded`、`rejected`、`cancelled`、
`expired` 和 `failed`，不包含已被新版本替换的旧卡。

恢复追踪份量调整等操作产生的替换链。打开历史对话时同时核实这些状态，不根据旧消息
重建卡片；恢复失败仍可阅读消息，但需明确提示状态未核实。重新打开可重试。
同一确认单和版本的批准请求使用稳定的幂等键，跨客户端重建保持一致；服务器以现有
事务、行锁、版本与幂等记录保证不会重复执行。

## 7. 训练中调整与自主训练

`POST /api/v1/workouts` 可不传 `calendar_event_id`、`plan_day_id` 来开始自主训练。
训练响应补充这两个可空字段，前端据此区分“计划训练”的临时动作和“自主训练”的下一个动作。
已有训练创建、组记录和结束接口保持兼容。

`PATCH /api/v1/workouts/{workout_id}/exercises/{item_id}/target` 接收
`expected_workout_version`，以及至少一个 `target_sets`（1–20）、`rest_seconds`（0–1800）。
只修改该场训练的动作快照，不改训练计划、日历内容快照或已完成组。
目标组数不得低于已完成组数；0 秒休息表示关闭倒计时。
所有权、进行中状态和版本均在后端校验；版本冲突返回 409，目标不合法返回 422。

动作快照的实际组数字段仍为 `target_snapshot.sets`；前端兼容原先的 `target_sets`。
`rest_timer` 继续由最新有效完成组推导；修改休息时长后，从该组完成时计算。
训练暂停时保留剩余时长，继续时延后截止时间；恢复页面可重新读取。
组删除使用既有作废记录机制，新组从包含作废记录的最大序号之后追加，保留修订历史。

## 8. 饮水记录

饮水记录使用独立的 `water_entries` 表，迁移版本为 `b4e6a8c2d901`。
以下接口均要求登录，仅访问当前账号的数据：

- `POST /api/v1/nutrition/water`：要求 UUID 格式的 `Idempotency-Key`，请求为 `{ "amount_ml": 250, "consumed_at": "2026-10-23T10:00:00+08:00" }`。毫升数为 1–5000 的整数，时间必须包含时区。成功返回 201 和 `id`、`amount_ml`、`consumed_at`；相同幂等请求重放原响应。
- `GET /api/v1/nutrition/water?date=2026-10-23`：按北京时间日期查询，返回按饮水时间倒序排列的记录数组。
- `DELETE /api/v1/nutrition/water/{entry_id}`：软删除当前账号的一条记录，成功返回 204；不存在、已删除或属于其他账号时返回 404。

`GET /api/v1/nutrition/daily-summary` 新增整数 `water_ml`，表示当天未删除饮水记录的累计毫升数，无记录时为 0。饮水不影响热量、三大营养素、餐食数量及餐食记录完整度。

AI 饮水使用 `water_record_draft` 意图和 `propose_water_entry` 工具，生成
`water_entry_create` 确认卡，`after.water` 包含 `amount_ml`、带时区的 `consumed_at`。
通过既有确认接口批准后才写入饮水；修订待确认草稿沿用通用草稿替换流程。
只读工具 `read_water_entries(day)` 返回该北京时间日期的记录和 `water_ml` 合计。

## 9. 营养目标与历史补记

每日营养 `target` 继续使用 `kcal_min/kcal_max` 和
`protein_min_g/protein_max_g`、`carbs_min_g/carbs_max_g`、`fat_min_g/fat_max_g`。
移动端展示上下限区间，圆环按上限计算进度，无目标时明确显示未设置。
`recorded_meals` 按早餐、午餐、晚餐顺序返回已记录的主餐类型；
`record_completeness` 为不同主餐类型数量除以 3，四舍五入到两位。
同一餐重复记录以及加餐不增加此覆盖值。每周覆盖度仍表示记录天数除以 7。

- `GET /api/v1/nutrition/entries/recent?date=2026-10-23&limit=20`：返回当前账户指定日期及之前最近的未删除餐食，默认 20 条，最多 50 条；按时间倒序。
- `POST /api/v1/nutrition/entries/{entry_id}/copy`：要求 `Idempotency-Key`。请求字段为 `expected_version`、`meal_type`、带时区的 `eaten_at`。201 返回新餐食；校验原餐所有权及版本，完整复制原食品、份量和营养快照，不受食品库后续修改影响。原餐不存在返回 404，原餐版本变化返回 409。

移动端允许为今天和过去日期记三餐、加餐、手动营养、餐食照片与饮水。
打开入口时固定记录日期，后续导航不会改写；历史餐次采用北京时间的常见餐时。
复制入口先选择最近餐食，再展示目标日期、可选餐次、食物份量和总热量，点击确认后保存。

## 离线记录的客户端约束（2026-11-02）

移动端只对新增饮食、饮水、身体测量和已开始训练的新增组使用本机持久队列。排队时固定原始发生时间、请求内容和 Idempotency-Key，先安全写入本机再发送；登录凭据不进入队列。服务端确认以前，客户端显示待同步状态，不将本机记录冒充服务端统计。

训练组响应新增可空 `client_generated_id`，值为原始创建请求的标识；当前训练内的组也返回这一字段，供响应丢失后的页面去重。旧客户端可忽略该字段。

通用幂等记录保留 24 小时；客户端对已尝试提交达 23 小时的未确认项停止自动重试，提示先核对。未发出过请求的离线记录不受这一首次提交限制。冲突、权限、输入错误会留在本机等待处理，网络/超时/繁忙则保留同一标识待重试。确认卡、AI 请求、修改及删除不进入自动写入队列。
