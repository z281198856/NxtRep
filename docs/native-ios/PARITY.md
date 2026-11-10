# Flutter → SwiftUI 功能对齐清单

基准：Flutter 源码 `b6df170`。范围为用户实际能够进入的页面与操作，包括前端本地能力；不以入口数量或后端已有路由代替功能完成。

接口基线见 [flutter-api-baseline.json](flutter-api-baseline.json)：35 个展示相关源文件、117 个去重接口操作。该清单记录来源和源码摘要，后续 Flutter 变更须重新核对。方法存在仅说明有实现，不能推导成设备验收通过。

状态：`缺失`、`开发中`、`已实现待验证`、`自动验证通过`、`真机通过`。每行须同时核对功能代码、接口/本地存储、错误恢复及验收证据。

| 编号 | 模块与原有功能 | Flutter 来源 | 初始 SwiftUI 状态 |
| --- | --- | --- | --- |
| AUTH-01 | 登录、退出、刷新令牌、重开恢复 | auth_repository / auth_gate | 真机通过（0.2.0） |
| AUTH-02 | 首次设密、资料初始化与目标检查 | password_setup_page / onboarding_page | 缺失 |
| AUTH-03 | 改密、会话列表、撤销单设备及其他设备 | account_security_page | 缺失 |
| HOME-01 | 共享日期、当天训练、进行中训练恢复 | home_shell / today_page | 缺失 |
| HOME-02 | 今日营养范围、饮水圆环、实际目标 | today_page / nutrition_page | 部分真机通过，日期与全量状态待补 |
| HOME-03 | 快速入口、记录同步提示、提醒导航 | home_shell | 缺失 |
| FOOD-01 | 真实食品搜索、完整分页、来源与营养基准 | food_library_page / nutrition_repository | 缺失（3 条演示） |
| FOOD-02 | 常用食品、条码查询、食品详情与份量换算 | food_library_page | 缺失 |
| FOOD-03 | 自定义食品、按份量记录、餐次/日期/备注 | food_library_page / nutrition_repository | 缺失 |
| EX-01 | 动作完整分页、关键词/器械/肌群筛选 | exercise_library_page | 缺失（3 条演示） |
| EX-02 | 动作步骤、呼吸、常见错误、安全提示、替代动作 | exercise_library_page | 缺失 |
| EX-03 | 动态解剖：41 种动作、器械差异、主辅肌群、方向、暂停/减少动态 | anatomy_motion_illustration | 缺失 |
| EX-04 | 动作历史及历史组、自定义动作增改删 | exercise_library_page / exercise_repository | 缺失 |
| PLAN-01 | 官方模板、详情、按目标/训练条件推荐 | template_catalog_page / plan_controller | 缺失 |
| PLAN-02 | 模板生成草稿、校验、提交、确认启用 | training_repository | 缺失 |
| PLAN-03 | 自建计划、AI 生成、文字导入、图片导入 | custom_plan_page | 缺失 |
| PLAN-04 | 当前计划、周安排、计划详情 | active_plan_detail_page / plan_page | 缺失 |
| CAL-01 | 日历日期切换、训练事件列表与详情、新建事件 | training_calendar / calendar_event_detail_page | 缺失 |
| CAL-02 | 缺练改期、顺延/跳过策略、训练时间压缩及确认 | calendar_event_detail_page | 缺失 |
| WORK-01 | 自主/按计划开练、进行中训练恢复、状态/时长 | workout_page / training_controller | 缺失（本地计时演示） |
| WORK-02 | 动作选择、增加/替换/跳过、目标组次调整 | workout_page | 缺失 |
| WORK-03 | 组记录增改删、重量/次数/RIR/RPE/备注、热身组 | workout_page / training_repository | 缺失 |
| WORK-04 | 组间休息计时、暂停/继续、放弃、完成总结 | workout_page | 缺失 |
| WORK-05 | 训练历史分页与详情 | workout_history_page | 缺失 |
| NUT-01 | 按日汇总、餐次、完整饮食记录与周汇总 | nutrition_page / nutrition_history tests | 缺失（首页汇总已接入） |
| NUT-02 | 手动饮食录入、修改、删除确认 | nutrition_page / nutrition_repository | 缺失 |
| NUT-03 | 最近餐食、跨日/餐次复制 | nutrition_copy_sheet | 缺失 |
| NUT-04 | 饮水自选数量/时间、列表与删除 | water_entry_sheet | 部分真机通过（固定 250ml） |
| NUT-05 | 拍照估算、说明/修正、重新估算、逐项核对与保存 | nutrition_photo_page | 缺失（仅本机相册预览） |
| NUT-06 | 文字饮食识别、草稿核对与确认 | nutrition_tools_page | 缺失 |
| NUT-07 | 饮食建议、灵活餐创建与列表 | nutrition_tools_page | 缺失 |
| NUT-08 | 食谱列表与新增 | nutrition_tools_page | 缺失 |
| BODY-01 | 测量增改、日期/体重/围度/体脂/测量条件与备注 | progress_page / body_repository | 缺失 |
| BODY-02 | 趋势、指标选择、日期范围、个人纪录 | progress_page | 缺失 |
| BODY-03 | 海军围度法估算、局限说明、保存与历史 | navy_body_fat_sheet | 缺失 |
| PHOTO-01 | 身体照片上传/查看、时间/视角/备注 | body_progress_page | 缺失 |
| PHOTO-02 | 身体照片评估、前后对比、结果局限与建议 | body_progress_page | 缺失 |
| REPORT-01 | 阶段报告生成、历史、详情与来源 | body_progress_page | 缺失 |
| AI-01 | 新建/选择会话、历史分页、重命名/归档/删除 | agent_page / conversation_history | 缺失 |
| AI-02 | 真正的流式回复、处理状态、工具事件与来源链接 | agent_page / agent_controller | 缺失（固定建议） |
| AI-03 | 图文提问、上下文提示、输入草稿恢复 | agent_page / image_upload | 缺失 |
| AI-04 | 确认卡、查看影响、批准/拒绝、过期/版本冲突处理 | agent_page / agent_repository | 缺失 |
| AI-05 | 未确认草稿、确认列表、记忆列表/删除/清空 | agent_management_page | 缺失 |
| AI-06 | 流中断结果核实、取消、历史恢复与避免重复发送 | agent_controller / agent_repository | 缺失 |
| COACH-01 | 主动建议列表、已读/忽略、按类型处理 | proactive_controller / proactive_repository | 缺失 |
| COACH-02 | 主动教练与提醒设置 | profile_page / proactive_repository | 缺失 |
| PROFILE-01 | 个人资料编辑、单位换算 | profile_page / profile_repository | 缺失 |
| PROFILE-02 | 训练目标、器械、频率、时长、目标检查 | profile_page / profile_repository | 缺失 |
| PROFILE-03 | 单位、隐私、匿名分析偏好及实际应用 | profile_page / app_preferences | 缺失 |
| REM-01 | 本机通知权限、总/分类开关、训练/三餐/饮水/测量 | local_reminders_page | 缺失 |
| REM-02 | 时间/星期/多次饮水、勿扰、隐藏内容、测试提醒 | local_reminders_page / reminder_controller | 缺失 |
| REM-03 | 重开恢复、账号隔离、退出清理、通知点击导航 | reminder_platform / home_shell | 缺失 |
| OFF-01 | 新增饮食/饮水/测量/训练组的持久离线队列 | local_records / api_client | 缺失 |
| OFF-02 | 固定发生时间与幂等键、23小时边界、冲突暂停 | local_records | 缺失 |
| OFF-03 | 待同步/失败状态、手动重试/丢弃、重连同步 | local_records_page / home_shell | 缺失 |
| OFF-04 | 表单/AI/照片输入草稿、按账号隔离、退出处理 | form_draft / local_records | 缺失 |
| MEDIA-01 | HEIC/JPEG 规范化、尺寸限制、上传意图/直传/完成 | core/media/image_upload | 缺失 |
| MEDIA-02 | 图片下载意图、过期重新获取、来源链接 | body_progress_repository / source_links | 缺失 |

## 实施与验证顺序

1. 共用 API、版本/确认机制、完整目录与动态动作。
2. 饮食/训练/日历的真实读写，以及首页真实数据与共享日期。
3. 身体进展、图片、报告、个人资料与账户安全。
4. AI 流式会话、确认/草稿/记忆与主动教练。
5. 提醒、本机草稿与离线队列、系统偏好和恢复。
6. 对照上述每行验证，并在 iPhone 验收；缺少证据的项保持未验收。

不改变原 Flutter 的业务基准，不使用演示行、通用说明页或隐藏入口代替迁移。SwiftUI 可以调整信息层级与交互，但须保留原操作、数据及恢复语义。

核对修正：数据导出与账号注销存在后端路由，但当前 Flutter 没有提供对应用户入口，因此不计入本次前端对齐基线。
