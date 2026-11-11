# Flutter → SwiftUI 功能对齐清单

基准：Flutter 源码 `b6df170`。范围为用户实际能够进入的页面与操作，包括前端本地能力；不以入口数量或后端已有路由代替功能完成。

接口基线见 [flutter-api-baseline.json](flutter-api-baseline.json)：35 个展示相关源文件、117 个去重接口操作。该清单记录来源和源码摘要，后续 Flutter 变更须重新核对。方法存在仅说明有实现，不能推导成设备验收通过。

状态：`缺失`、`开发中`、`已实现待验证`、`自动验证通过`、`真机通过`。每行须同时核对功能代码、接口/本地存储、错误恢复及验收证据。

| 编号 | 模块与原有功能 | Flutter 来源 | 初始 SwiftUI 状态 | 当前实现与验证 |
| --- | --- | --- | --- | --- |
| AUTH-01 | 登录、退出、刷新令牌、重开恢复 | auth_repository / auth_gate | 真机通过（0.2.0） | 0.2.0 真机通过；0.3.0 待复验 |
| AUTH-02 | 首次设密、资料初始化与目标检查 | password_setup_page / onboarding_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AUTH-03 | 改密、会话列表、撤销单设备及其他设备 | account_security_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| HOME-01 | 共享日期、当天训练、进行中训练恢复 | home_shell / today_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| HOME-02 | 今日营养范围、饮水圆环、实际目标 | today_page / nutrition_page | 部分真机通过，日期与全量状态待补 | 已实现，0.3.0 编译通过；真机待验 |
| HOME-03 | 快速入口、记录同步提示、提醒导航 | home_shell | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| FOOD-01 | 真实食品搜索、完整分页、来源与营养基准 | food_library_page / nutrition_repository | 缺失（3 条演示） | 已实现，0.3.0 编译通过；真机待验 |
| FOOD-02 | 常用食品、条码查询、食品详情与份量换算 | food_library_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| FOOD-03 | 自定义食品、按份量记录、餐次/日期/备注 | food_library_page / nutrition_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| EX-01 | 动作完整分页、关键词/器械/肌群筛选 | exercise_library_page | 缺失（3 条演示） | 已实现，0.3.0 编译通过；真机待验 |
| EX-02 | 动作步骤、呼吸、常见错误、安全提示、替代动作 | exercise_library_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| EX-03 | 动态解剖：41 种动作、器械差异、主辅肌群、方向、暂停/减少动态 | anatomy_motion_illustration | 缺失 | 138 个分类差分用例、41 类姿态数据通过；真机待验 |
| EX-04 | 动作历史及历史组、自定义动作增改删 | exercise_library_page / exercise_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PLAN-01 | 官方模板、详情、按目标/训练条件推荐 | template_catalog_page / plan_controller | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PLAN-02 | 模板生成草稿、校验、提交、确认启用 | training_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PLAN-03 | 自建计划、AI 生成、文字导入、图片导入 | custom_plan_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PLAN-04 | 当前计划、周安排、计划详情 | active_plan_detail_page / plan_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| CAL-01 | 日历日期切换、训练事件列表与详情、新建事件 | training_calendar / calendar_event_detail_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| CAL-02 | 缺练改期、顺延/跳过策略、训练时间压缩及确认 | calendar_event_detail_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| WORK-01 | 自主/按计划开练、进行中训练恢复、状态/时长 | workout_page / training_controller | 缺失（本地计时演示） | 已实现，0.3.0 编译通过；真机待验 |
| WORK-02 | 动作选择、增加/替换/跳过、目标组次调整 | workout_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| WORK-03 | 组记录增改删、重量/次数/RIR/RPE/备注、热身组 | workout_page / training_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| WORK-04 | 组间休息计时、暂停/继续、放弃、完成总结 | workout_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| WORK-05 | 训练历史分页与详情 | workout_history_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| NUT-01 | 按日汇总、餐次、完整饮食记录与周汇总 | nutrition_page / nutrition_history tests | 缺失（首页汇总已接入） | 已实现，0.3.0 编译通过；真机待验 |
| NUT-02 | 手动饮食录入、修改、删除确认 | nutrition_page / nutrition_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| NUT-03 | 最近餐食、跨日/餐次复制 | nutrition_copy_sheet | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| NUT-04 | 饮水自选数量/时间、列表与删除 | water_entry_sheet | 部分真机通过（固定 250ml） | 已实现，0.3.0 编译通过；真机待验 |
| NUT-05 | 拍照估算、说明/修正、重新估算、逐项核对与保存 | nutrition_photo_page | 缺失（仅本机相册预览） | 已实现，0.3.0 编译通过；真机待验 |
| NUT-06 | 文字饮食识别、草稿核对与确认 | nutrition_tools_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| NUT-07 | 饮食建议、灵活餐创建与列表 | nutrition_tools_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| NUT-08 | 食谱列表与新增 | nutrition_tools_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| BODY-01 | 测量增改、日期/体重/围度/体脂/测量条件与备注 | progress_page / body_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| BODY-02 | 趋势、指标选择、日期范围、个人纪录 | progress_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| BODY-03 | 海军围度法估算、局限说明、保存与历史 | navy_body_fat_sheet | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PHOTO-01 | 身体照片上传/查看、时间/视角/备注 | body_progress_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PHOTO-02 | 身体照片评估、前后对比、结果局限与建议 | body_progress_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| REPORT-01 | 阶段报告生成、历史、详情与来源 | body_progress_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AI-01 | 新建/选择会话、历史分页、重命名/归档/删除 | agent_page / conversation_history | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AI-02 | 真正的流式回复、处理状态、工具事件与来源链接 | agent_page / agent_controller | 缺失（固定建议） | 已实现，0.3.0 编译通过；真机待验 |
| AI-03 | 图文提问、上下文提示、输入草稿恢复 | agent_page / image_upload | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AI-04 | 确认卡、查看影响、批准/拒绝、过期/版本冲突处理 | agent_page / agent_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AI-05 | 未确认草稿、确认列表、记忆列表/新增/编辑/删除 | agent_management_page | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| AI-06 | 流中断结果核实、取消、历史恢复与避免重复发送 | agent_controller / agent_repository | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| COACH-01 | 主动建议列表、已读/忽略、按类型处理 | proactive_controller / proactive_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| COACH-02 | 主动教练与提醒设置 | profile_page / proactive_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PROFILE-01 | 个人资料编辑、单位换算 | profile_page / profile_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PROFILE-02 | 训练目标、器械、频率、时长、目标检查 | profile_page / profile_repository | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| PROFILE-03 | 单位、隐私、匿名分析偏好及实际应用 | profile_page / app_preferences | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| REM-01 | 本机通知权限、总/分类开关、训练/三餐/饮水/测量 | local_reminders_page | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| REM-02 | 时间/星期/多次饮水、勿扰、隐藏内容、测试提醒 | local_reminders_page / reminder_controller | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| REM-03 | 重开恢复、账号隔离、退出清理、通知点击导航 | reminder_platform / home_shell | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| OFF-01 | 新增饮食/饮水/测量/训练组的持久离线队列 | local_records / api_client | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| OFF-02 | 固定发生时间与幂等键、23小时边界、冲突暂停 | local_records | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| OFF-03 | 待同步/失败状态、手动重试/丢弃、重连同步 | local_records_page / home_shell | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| OFF-04 | 表单/AI/照片输入草稿、按账号隔离、退出处理 | form_draft / local_records | 缺失 | 代码与恢复核心自动检查通过；完整页面真机待验 |
| MEDIA-01 | HEIC/JPEG 规范化、尺寸限制、上传意图/直传/完成 | core/media/image_upload | 缺失 | 已实现，0.3.0 编译通过；真机待验 |
| MEDIA-02 | 图片下载意图、过期重新获取、来源链接 | body_progress_repository / source_links | 缺失 | 已实现，0.3.0 编译通过；真机待验 |

## 实施与验证顺序

1. 共用 API、版本/确认机制、完整目录与动态动作。
2. 饮食/训练/日历的真实读写，以及首页真实数据与共享日期。
3. 身体进展、图片、报告、个人资料与账户安全。
4. AI 流式会话、确认/草稿/记忆与主动教练。
5. 提醒、本机草稿与离线队列、系统偏好和恢复。
6. 对照上述每行验证，并在 iPhone 验收；缺少证据的项保持未验收。

不改变原 Flutter 的业务基准，不使用演示行、通用说明页或隐藏入口代替迁移。SwiftUI 可以调整信息层级与交互，但须保留原操作、数据及恢复语义。

核对修正：数据导出与账号注销存在后端路由，但当前 Flutter 没有提供对应用户入口，因此不计入本次前端对齐基线。

## 0.3.0 实现与证据（2026-11-10）

安装包代码：`e94e182b45a31fdf8c2ef48d6ce45ff56def3aa8`，版本 `0.3.0 (3)`。
[GitHub Actions 构建与日志](https://github.com/z281198856/NxtRep/actions/runs/42820732556)通过，包含 16 组原生客户端和恢复检查，以及 Release / iphoneos / arm64 编译。编译通过不代表全部业务操作已在手机上验收。

| 模块 | SwiftUI 实现 |
| --- | --- |
| 主界面与真实入口 | `NativeAppShell.swift`、`NativeConnectionView.swift` |
| 全量目录与动作解析 | `NativeCatalogViews.swift`、`NativeAnatomyMotion.swift`、`FlutterMotionData.json` |
| 饮食、饮水、复制与工具 | `NativeNutritionViews.swift`、`NativeMedia.swift` |
| 计划、模板与日历调整 | `NativePlanViews.swift` |
| 开练、组记录、计时与训练历史 | `NativeWorkoutViews.swift` |
| 测量、趋势、照片与报告 | `NativeProgressViews.swift` |
| 流式教练、历史、确认单、记忆 | `NativeAgent.swift`、`NativeAgentViews.swift` |
| 主动建议、反馈与教练设置 | `NativeCoachViews.swift` |
| 账户、资料、单位与隐私 | `NativeProfileViews.swift` |
| 系统提醒及点击导航 | `NativeReminders.swift`、`NativeReminderModels.swift` |
| 加密队列、照片与表单草稿 | `NativeLocalStore.swift`、`NativeLocalViews.swift` |

验证记录：

- `Tests/APIContractChecks.swift` 与 `Tests/PersistenceChecks.swift`：16 组通过，覆盖数值与分页、URL 编码、刷新合并、幂等重试、SSE 边界、提醒计划、密文恢复、账号/服务器隔离、照片草稿、冲突暂停、23 小时边界及损坏数据保留。
- `python ios-native/Tools/export_flutter_motion.py --check`：138 个分类用例与原 Dart 分类器一致；41 种动作全部采样姿态与 Flutter 原公式一致。此项检查姿态数据及分类，不代表两端绘制像素完全相同。
- `python ios-native/Tools/check_api_routes.py`：53 个静态命名操作与正在运行的 OpenAPI 路径及 HTTP 方法一致。含动态 ID 的操作仍需契约和设备验证，不能用该数字推导全部操作成功。
- 本地 API 只读检查：登录、目录、档案、目标、营养、日历、进展、报告、提醒设置、记忆与会话均正常；检查使用独立登录会话，结束后注销该会话。
- 目录当前实际可见：35 个食品、74 个动作、85 个训练模板。SwiftUI 分页读取服务端完整可见结果；食品库扩充仍需要后端补充真实数据来源。
- IPA 已核对版本、bundle ID、arm64、相机/本地网络声明、受限 ATS、编译后图标与 41 类动作资源。

安装已通过 iloader 完成，并从 iPhone 设备接口核对实际版本为 `0.3.0 (3)`；重新签名后的相机和本地网络声明也已核对。安装成功仍不等于业务验收成功。

设备端仍需逐项确认：登录与重开、首页/共享日期、目录分页与动态动作、真实记录增改删、训练完成、计划确认、照片上传/AI 返回、流中断核实、离线同步、通知权限/触发/点击导航。新接入的 AI 和视觉能力还没有本轮真机成功证据。

0.3.0 首轮真机验证覆盖登录恢复、资料与设置、营养与饮水、计划和日历。手机新增饮水返回 201，随后读取饮水列表返回 200。动作库首屏发送了空关键词，服务器返回 422，用户报告动作未展示。

0.3.1（构建号 4，`aa2f60f`）省略空白动作筛选，已通过 17 组客户端检查和 iPhone Release 编译。本地接口验证覆盖全量列表、器械筛选和中文搜索。iPhone 安装后，动作列表、器械筛选和详情请求均返回 200。动画显示待真机确认。[构建记录](https://github.com/z281198856/NxtRep/actions/runs/42822743005)

0.3.2（构建号 5，`8b050cb`）让聊天输入区固定在消息列表下方。点新对话后即可输入，发送首条消息时创建服务端会话。18 组客户端检查覆盖了首次发送、流式回复和会话草稿。iPhone 已安装该版本，已有会话中的手机发消息请求返回 200，后端保存了用户消息与 AI 回复。新对话首次发送和回复在屏幕上的显示待真机确认。[构建记录](https://github.com/z281198856/NxtRep/actions/runs/42947887578)
