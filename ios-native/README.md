# NxtRep 原生 iOS 客户端

SwiftUI 客户端面向 iOS 18 及以上的 iPhone，与 Flutter 共用 FastAPI 后端。登录后的六个主页面已切换为真实业务：训练计划与日历、食品和动作库、饮食与饮水、训练记录、身体进展、AI 私人教练、账号与系统提醒。界面预览仅保留在登录页的显式体验入口。

## 0.3.0 功能对齐构建（2026-11-10）

`e94e182` / `0.3.0 (3)` 已通过 [GitHub Actions](https://github.com/z281198856/NxtRep/actions/runs/42820732556) 的 16 组客户端与恢复检查及 iPhone Release 编译；逐项实现、证据及真机待验边界见 [功能对齐清单](../docs/native-ios/PARITY.md)。这轮构建已通过 iloader 安装到 iPhone，并从设备接口核对版本；业务页面正在验收，尚不能据此宣称全部功能真机通过。

`0.3.1 (4)` 修复真机动作库首屏因空关键词加载失败的问题。17 组客户端检查和 Release 编译已通过。iPhone 上的动作列表、器械筛选和详情请求均返回 200，动画显示待确认。[0.3.1 构建记录](https://github.com/z281198856/NxtRep/actions/runs/42822743005)

`0.3.2 (5)` 增加固定聊天输入区，点击新对话即可输入，发送首条消息时创建会话。18 组客户端检查和 Release 编译已通过。iPhone 已安装，后端确认保存了手机发送的消息和 AI 回复。新对话首次发送和回复的屏幕显示待真机确认。[0.3.2 构建记录](https://github.com/z281198856/NxtRep/actions/runs/42947887578)

- 目录读取服务端完整可见数据；动作示意复用 Flutter 的 41 类姿态，138 个分类用例通过差分检查。
- 饮食、饮水、测量和训练组的新增操作先写入按账号和服务器隔离的加密日志，再提交服务器；重试保留时间与幂等标识，冲突和超期记录停止自动重放。
- 表单、AI 输入和照片草稿加密保存在本机。待同步的原表单会锁定，避免关闭重开后重复提交；照片密文单独存储，避免每次输入都重写照片。
- AI 使用真实 SSE 会话，支持历史、图片、结果核实、取消、确认单和长期记忆；计划和记录修改仍需用户确认。
- 本机系统提醒包含训练、三餐、饮水与测量，支持星期、多个时间、勿扰和内容隐藏；退出撤销本机安排，同一账号重开后恢复。

## 0.2.0 本地真机验收（2026-11-09）

代码提交 `308c872`，构建号 2。[Codemagic 真机构建](https://codemagic.io/build/6af18fad24e1ec237557d941)成功，iPhone 16 上实际安装的版本及本地网络声明已通过设备接口核对。

| 验收项 | 结果与依据 |
| --- | --- |
| Windows 本地后端与数据库 | 就绪检查通过；手机 Safari 实际访问返回 `ready` |
| Swift 客户端检查 | 4 项通过，覆盖地址限制、Decimal/目标范围解码、并发刷新和不确定饮水请求的幂等重试 |
| 本地启动与饮水请求校验 | 17 项 Python 测试通过；另完成真实登录、饮水写入、幂等重放、统计更新及轮换续期验证，临时测试记录已清理 |
| App 内真实登录与首页读取 | 用户真机确认；手机发出的登录、营养汇总和饮水读取均返回 HTTP 200 |
| 保存饮水 | 手机新增 250 毫升，后端返回 201；只读核对得到 1 条 250 毫升记录，汇总一致 |
| 关闭后恢复 | 用户从多任务关闭并重开后仍保持登录，饮水记录仍在；后端确认刷新凭证及重新读取均返回 HTTP 200 |

这次验收限定登录、首页营养与饮水。它不代表训练、饮食录入、AI 教练等其他页面已接入，也不代表云端部署、离线队列或外网使用已完成。电脑后端仍需运行，USB 联调仍需保持数据线和 USB 热点网络连接。

## Windows 与 iPhone 本地联调

在仓库根目录执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Local.ps1 -BackendOnly -Lan`。已有回环 API 时添加 `-RestartBackend`，显式切换为网络监听；不传 `-Lan` 时仍只监听 `127.0.0.1`。复用现有数据库，不清空账号或业务记录。

USB 联调需要 iPhone 的个人热点已通过数据线提供网络，Windows 中能看到 `Apple Mobile Device Ethernet`。以管理员运行 `scripts/Enable-iOSUsbNetwork.ps1`，只向该 USB 网卡的手机网关地址开放本机 API 的 TCP 8000 端口。脚本不开放数据库端口、不更改网络类型，也不修改其他防火墙规则。停用规则可在管理员 PowerShell 执行 `Remove-NetFirewallRule -Name NxtRep-iPhone-USB-API`。

用 iPhone Safari 打开 `http://<电脑的 Apple USB IPv4 地址>:8000/api/v1/health/ready`，确认返回 `ready`。App 登录页的服务器地址填 `http://<电脑地址>:8000/api/v1`，使用 **NxtRep 账号**登录，并允许本地网络访问。保持电脑和后端运行；USB 联调时保持数据线及 USB 热点网络连接。

本机专用联调账号由 `scripts/Local-TestAccount.ps1 -Setup` 创建或复用，凭据通过 Windows DPAPI 加密保存。按 `scripts/README.md` 的本机查看方法获取，不将密码、数据库 URL 或模型密钥写入 Swift、CI 变量或 Git。

客户端使用 URLSession 访问接口，刷新令牌存入 Keychain，访问令牌只保存在内存。并发失效请求合并刷新；401 后最多续期与重放一次。新增记录附带持久幂等标识；响应不确定时沿用同一份时间、内容和标识，队列与表单可跨 App 重开恢复。营养值兼容后端 Decimal 字符串；未设置个人目标时不使用演示目标填充圆环。

HTTP 仅用于本地地址；公网服务器必须使用 HTTPS。`LocalNetwork.plist` 声明本地网络用途，ATS 例外限定 RFC1918 IPv4 网段及回环地址。见 [Apple 本地网络例外](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking)。

真机工作流会先在 Mac 上运行 `Tests/APIContractChecks.swift`，验证数值解码、地址限制、并发令牌刷新以及饮水重试的幂等标识，再编译 IPA。完整验收还需要按照功能对齐清单在手机上执行实际业务，核对数据库结果与失败恢复。

## 在 Codemagic 编译

1. 将包含 `ios-native/` 和根目录 `codemagic.yaml` 的分支推送到 GitHub。
2. 在 Codemagic 个人工作区添加该 GitHub 仓库，使用 `codemagic.yaml` 配置。若工作流尚未识别，选中该分支后点击 **Check for configuration file**。
3. 点击 **Start new build**，选中该分支和 **NxtRep Native iOS Simulator**（`native-ios-simulator`），点击 **Start new build**。
4. 构建成功后，在 **Artifacts** 下载 `NxtRepNative-simulator.zip`。附加产物压缩包中包含原生首页截图 `NxtRepNative-home.png` 和编译日志 `xcodebuild.log`，可在 Windows 上查看。

工作流使用 Mac mini M2 和 Xcode 26.0 镜像，在预装的 iPhone 16（iOS 18.5）模拟器中启动 App 并截图。编译或截图失败时，构建详情会标出失败步骤。此流程可使用个人账户的 M2 免费构建额度，截图也在同一次构建中生成。 [Codemagic 镜像规格](https://docs.codemagic.io/specs-macos/xcode-26-0/) · [YAML 工作流](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/) · [构建额度](https://docs.codemagic.io/billing/pricing/)

模拟器编译无需 Apple Developer 会员或签名证书。产物解压后是 `NxtRepNative.app`，可在兼容的 macOS iOS 模拟器中运行。 [iOS 模拟器构建](https://docs.codemagic.io/yaml-code-signing/ios-simulator-builds/)

## 安装到自己的 iPhone

当前项目可通过 `.github/workflows/native-ios.yml` 的 **Native iOS parity checks** 构建，或使用现有 Codemagic `native-ios-device` 工作流。两种流程均输出未签名的真机 IPA，需要在本机通过个人 Apple 账户签名后才能安装。

本机已使用 iloader 2.4.1 成功安装过 0.2.0。更新流程为：

1. 保持 iPhone 通过数据线连接、解锁并信任电脑。
2. 打开 iloader，在本机完成 Apple 账户登录和验证；不把密码或验证码写入项目或 CI。
3. 选择 USB iPhone，使用 **Import IPA** 导入本次构建的 IPA 并等待签名和安装完成。
4. 在手机打开 NxtRep；需要时按系统提示信任开发者并开启开发者模式。使用 NxtRep 账号登录，与安装签名使用的 Apple 账号区分。
5. 按功能清单验收实际读写、AI、离线恢复及系统提醒。安装完成与这些功能通过是不同的状态。

个人签名需要按签名工具与 Apple 的规则定期续期。云端构建不会把本机后端部署到公网；联调时仍需保持电脑、API 和 USB 网络运行。

## 在 Mac 上查看界面

在 Xcode 16 或更新版本中打开 `ios-native/NxtRepNative.xcodeproj`，选择 `NxtRepNative` scheme 和 iPhone 16 模拟器，点击 Run。若已有 Codemagic 构建包，也可以解压后在启动了 iPhone 16 模拟器的 Mac 上，从解压目录执行以下命令。

```bash
xcrun simctl install booted NxtRepNative.app
xcrun simctl launch booted com.zengsiqi.nxtrep.native
```
