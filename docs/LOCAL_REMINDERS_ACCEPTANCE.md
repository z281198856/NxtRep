# 手机本机定时提醒：实现与验收

本轮范围是用户选择的“本机定时提醒”。入口：**我的 → 手机系统提醒**。新安装及新账户的总开关和各类开关均默认关闭；只有主动开启才请求系统通知权限。没有远程推送服务、AI 后台推送或新增服务端接口。

## 支持的行为

- 训练、早餐记录、午餐记录、晚餐记录、饮水、体重体脂记录六类提醒；分别选择时间和星期。饮水可设置 1–6 个时间。
- 总开关、免打扰时间、隐藏通知内容、通知权限状态、系统设置入口、下一批提醒预览及约 10 秒的测试提醒。
- 点击训练提醒进入今日训练；餐食提醒进入当天饮食；饮水提醒打开记饮水表单；身体数据提醒打开体重/体脂表单。点击不自动保存业务记录。
- 设置按服务器与账户隔离并加密保存在本机。退出登录取消这个功能已安排和已展示的通知，保留账户的设置供下次登录使用。换设备需要重新设置。
- 默认通知只显示“NxtRep 提醒 / 你设置的提醒时间到了，点按查看。”；关闭隐藏后显示通用类别文案，不包含体重、体脂或具体饮食数据。

## 原理和边界

`ReminderPlanner` 把本地时间、星期与免打扰配置变成稳定 ID 的重复任务；`FlutterReminderPlatform` 通过 `flutter_local_notifications` 交给 Android AlarmManager / iOS UNUserNotificationCenter。送达由操作系统执行，不依赖 Dart 常驻计时器，也不需要在提醒时请求后端。

Android 13+ 需允许通知；Android 使用普通的 `inexactAllowWhileIdle` 调度，没有申请精确闹钟权限。省电、系统免打扰及厂商后台策略可能推迟或限制通知，不能承诺秒级准时。重启后由原生 BOOT_COMPLETED 接收器恢复已保存的任务。普通后台进程回收与系统设置里的“强行停止”不同：强行停止会影响系统任务，需要重新打开 App 恢复。

App 每次回到前台核对权限、手机时区和已安排的 ID；时区变化后应重新打开 App。使用完整 IANA 时区表，兼容原生返回的 GMT、UTC、US/Eastern 等别名。免打扰会跳过**配置时间**落入时段的任务；系统延迟到达的通知仍受手机的系统免打扰策略控制。

iOS 最多安排 63 个重复任务并预留 1 个测试任务，超过预算会明确提示调整星期/时段，不会静默丢弃。iOS 接入代码已添加，但 Windows 环境没有做 iOS 构建和设备验收。

官方说明：[Android 闹钟调度](https://developer.android.com/develop/background-work/services/alarms)、[Android 通知授权](https://developer.android.com/develop/ui/compose/notifications/notification-permission)、[Android 停止状态](https://developer.android.com/about/versions/15/behavior-changes-all)、[Apple 本机通知](https://developer.apple.com/documentation/UserNotifications/scheduling-a-notification-locally-from-your-app)、[通知插件与平台配置](https://pub.dev/packages/flutter_local_notifications)。

## 自动化检查

在 `frontend` 目录执行：

```powershell
flutter --no-version-check test test/core/notifications/local_reminders_test.dart
flutter --no-version-check analyze
flutter --no-version-check test
```

**2026-11-02 结果：提醒专项 18 项通过，Flutter 全量 271 项通过，`flutter analyze` 无问题，Android 正常入口 Debug APK 构建成功。**

专项用例覆盖计划 ID 稳定性、选定星期、跨日/夏令时、免打扰边界、参数校验、任务预算、权限拒绝和通知渠道关闭、重复保存、撤销后恢复权限、账户和服务器隔离、退出登录与权限弹窗竞态、磁盘失败、原生部分安排失败与重试、初始化失败重试、损坏设置保留、冷启动点击校验、恢复前台时的点击竞态、测试提醒替换与取消，以及页面开关行为。原生适配器额外检查时区别名。

## 手机验收步骤

请使用测试账户。每项先观察通知栏和页面，再判定通过，避免只检查设置文件。

真机前提：使用已指向手机可访问 API 的测试包并完成登录。当前 Windows 启动器生成的包使用 `10.0.2.2` 连接本机后端，只适合 Android 模拟器；它不是可直接交付实体手机的发布包。真机包需要按部署环境设置 `API_BASE_URL`，发布环境使用 HTTPS。

| 场景 | 操作 | 通过标准 |
| --- | --- | --- |
| 首次默认 | 打开提醒页 | 总开关/类别关闭，没有重复任务；没有自动弹授权 |
| 拒绝授权 | 开启总开关，在系统弹窗选择不允许 | 页面提示未获准，总开关保持关闭，没有安排任务 |
| 恢复权限 | 点系统设置入口允许通知，再返回 | 权限状态自动刷新；仍由用户明确开启总开关 |
| 后台送达 | 开总开关和饮水，确认测试时间不在免打扰内，发送测试后回桌面 | 系统通知栏出现通知；允许普通调度延迟，记录实际时间 |
| 离线与进程回收 | 安排测试后断网、回桌面；让系统正常回收进程 | 通知仍能由系统出现；不要用“强行停止”模拟普通回收 |
| 点击跳转 | 点饮水通知；再分别测训练、餐食、身体数据 | 打开正确页面/表单，冷启动和已打开 App 均可，未自动保存记录 |
| 重复安排 | 多次保存同一时间或回到前台 | 任务数和 ID 稳定，同一个测试按钮替换旧测试任务 |
| 免打扰 | 把某个提醒时间放入免打扰区间 | 该配置时间不安排任务；免打扰内测试明确提示 |
| 系统撤权 | 在手机设置关闭通知，再回 App | 展示权限关闭；重新允许后按已保存配置恢复 |
| 关闭与退出 | 安排测试后立即关总开关；再测退出账户 | 待发任务与已展示提醒清除，等待后不再出现该测试通知 |
| 设备重启 | 安排日常提醒，正常重启；不先启动 App | 原生接收器恢复任务；在设定时段由系统送达 |
| 强行停止 | 在系统设置强行停止，再手动打开 App | 不把停止期间未送达判为普通后台失败；重开后配置恢复 |
| 真实手机 | 分别在常用 Android 品牌和 iPhone 锁屏等待 | 核对声音、锁屏隐私、勿扰、省电和后台限制；记录机型/系统版本 |

系统普通调度延迟没有统一的秒级验收阈值。约 10 秒测试用于快速检查整条链路；若没到，应核对权限、通知渠道、省电、系统勿扰及是否强行停止，再检查系统任务和日志。正式机型验收还应安排真实的日/周时间，观察一轮正常周期。

## 本轮实测记录

设备为 Pixel_8 / emulator-5554，Android 17 / API 37；使用正常 `main.dart` 入口和专用合成测试账户，未保存新的饮水或测量记录。

| 检查 | 结果与证据 |
| --- | --- |
| 默认与拒绝授权 | 总开关关闭、0 个任务；拒绝系统弹窗后仍关闭。`default-off.png`、`permission-denied.png` |
| 系统设置授权 | App 入口可打开 Android 通知设置；允许后返回，权限刷新，总开关保持关闭，手动开启才生效 |
| 真实日重复任务 | 5 个饮水任务在原生保存表和 `dumpsys alarm` 中均存在；ID 为 30400 / 30410 / 30420 / 30430 / 30440 |
| 后台与后端不可用 | 停用经归属核验的本地测试 API，回桌面后仅对测试 App 进程发送 SIGKILL（没有强行停止包）；确认进程消失。系统约在结束进程 9 秒后出现测试通知。`background.json`、`background-delivery.png` |
| 冷启动点击 | 点饮水通知后恢复账户并打开“记饮水”表单；此时后端仍不可用。未点保存。`cold-open-water.png` |
| 重启恢复 | 重启后不启动 App，观察到原生 BOOT_COMPLETED 接收器启动并恢复 5 个系统闹钟。开机状态属性就绪早于广播，第一次过早采样为 0，等待广播后为 5。`reboot.json`、`boot-logcat.txt`、`alarms-after-boot-broadcast-before-app.txt` |
| 强行停止与重开 | 强行停止包后系统闹钟为 0；重新打开 App 后恢复为 5。`reboot.json` |
| 关闭清理 | 测试任务安排后关总开关，原生待发、系统闹钟、已展示通知均为 0；等待原定时间过去后仍为 0。`cancel.json` |
| 退出账户 | 带测试任务退出登录，回到登录页；原定时间过后 3 项计数均为 0。重新登录后恢复账户的 5 个日常配置。`cancel.json`、`relogin.log` |
| 周重复与已打开 App 的点击 | 身体数据任务 ID 30501，原生重复类型 DayOfWeekAndTime；测试通知点开“记录身体数据”表单。截图核对有体重及可选体脂，未保存。`measurement.json`、`warm-open-measurement.png` |
| 最终清理 | 账户总开关关闭，原生待发数 / 系统闹钟数 / 活动通知数均为 0；测试 API 已恢复 ready。`report.json`、`final-reminders-off.png` |

所有本轮设备证据保存在本机 `.local/notifications-acceptance/`（Git 忽略），汇总是 [report.json](../.local/notifications-acceptance/report.json)。自动化日志：`.local/notifications-focused.log`、`.local/notifications-flutter-all.log`、`.local/notifications-analyze.log`。设备截图已实际查看；验收根据系统闹钟及活动通知核对，不只依赖插件的保存列表。

最终 APK 为 `.local/nxtrep-main-debug.apk`，源码摘要、缓存 APK 与模拟器安装的 base.apk 已核对一致：

```text
source SHA-256: 77ead1fb728800bb1f05c0b16c6096e5e1490e814d6caf9e48dbe9d38c4d055a
APK SHA-256: d093cb829e51190e1ef71a60d5c1cfe0b25a8a1c385e0f18f1b003f216df3fda
```

尚未验收：实体 Android 手机的锁屏/厂商省电策略、iOS 构建及实机、完整日/周周期的实际触发、六类通知逐一进行原生点击回归。当前已实测饮水冷启动和身体数据已打开 App 的点击链路；其余入口实现已接好，继续按上表在目标手机验收。这里的 Android 模拟器结果不表示生产发布就绪。
