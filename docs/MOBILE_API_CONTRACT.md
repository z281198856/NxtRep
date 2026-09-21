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
