# NxtRep 原生 iOS 预览

SwiftUI 客户端面向 iOS 18 及以上版本的 iPhone。支持连接现有 FastAPI 后端，完成登录、读取今日营养汇总、查看和新增饮水记录。计划、训练、进展、AI 教练等页面仍是明确标记的界面预览，尚未接入真实业务。登录页可选择离线体验原有预览。

## Windows 与 iPhone 本地联调

在仓库根目录执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Local.ps1 -BackendOnly -Lan`。已有回环 API 时添加 `-RestartBackend`，显式切换为网络监听；不传 `-Lan` 时仍只监听 `127.0.0.1`。复用现有数据库，不清空账号或业务记录。

USB 联调需要 iPhone 的个人热点已通过数据线提供网络，Windows 中能看到 `Apple Mobile Device Ethernet`。以管理员运行 `scripts/Enable-iOSUsbNetwork.ps1`，只向该 USB 网卡的手机网关地址开放本机 API 的 TCP 8000 端口。脚本不开放数据库端口、不更改网络类型，也不修改其他防火墙规则。停用规则可在管理员 PowerShell 执行 `Remove-NetFirewallRule -Name NxtRep-iPhone-USB-API`。

用 iPhone Safari 打开 `http://<电脑的 Apple USB IPv4 地址>:8000/api/v1/health/ready`，确认返回 `ready`。App 登录页的服务器地址填 `http://<电脑地址>:8000/api/v1`，使用 **NxtRep 账号**登录，并允许本地网络访问。保持电脑和后端运行；USB 联调时保持数据线及 USB 热点网络连接。

本机专用联调账号由 `scripts/Local-TestAccount.ps1 -Setup` 创建或复用，凭据通过 Windows DPAPI 加密保存。按 `scripts/README.md` 的本机查看方法获取，不将密码、数据库 URL 或模型密钥写入 Swift、CI 变量或 Git。

客户端使用 URLSession 访问接口，刷新令牌存入 Keychain，访问令牌只保存在内存。并发失效请求合并刷新；401 后最多续期与重放一次。饮水请求附带幂等标识，响应不确定时保留同一份时间、数量和标识供手动重试；它还不具备跨 App 退出的离线队列。营养值兼容后端 Decimal 字符串；未设置个人目标时不使用演示目标填充圆环。

HTTP 仅用于本地地址；公网服务器必须使用 HTTPS。`LocalNetwork.plist` 声明本地网络用途，ATS 例外限定 RFC1918 IPv4 网段及回环地址。见 [Apple 本地网络例外](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking)。

真机工作流会先在 Mac 上运行 `Tests/APIContractChecks.swift`，验证数值解码、地址限制、并发令牌刷新以及饮水重试的幂等标识，再编译 IPA。完整验收还需要在手机上登录、记录饮水，并重新打开 App 核对记录持久化。

## 在 Codemagic 编译

1. 将包含 `ios-native/` 和根目录 `codemagic.yaml` 的分支推送到 GitHub。
2. 在 Codemagic 个人工作区添加该 GitHub 仓库，使用 `codemagic.yaml` 配置。若工作流尚未识别，选中该分支后点击 **Check for configuration file**。
3. 点击 **Start new build**，选中该分支和 **NxtRep Native iOS Simulator**（`native-ios-simulator`），点击 **Start new build**。
4. 构建成功后，在 **Artifacts** 下载 `NxtRepNative-simulator.zip`。附加产物压缩包中包含原生首页截图 `NxtRepNative-home.png` 和编译日志 `xcodebuild.log`，可在 Windows 上查看。

工作流使用 Mac mini M2 和 Xcode 26.0 镜像，在预装的 iPhone 16（iOS 18.5）模拟器中启动 App 并截图。编译或截图失败时，构建详情会标出失败步骤。此流程可使用个人账户的 M2 免费构建额度，截图也在同一次构建中生成。 [Codemagic 镜像规格](https://docs.codemagic.io/specs-macos/xcode-26-0/) · [YAML 工作流](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/) · [构建额度](https://docs.codemagic.io/billing/pricing/)

模拟器编译无需 Apple Developer 会员或签名证书。产物解压后是 `NxtRepNative.app`，可在兼容的 macOS iOS 模拟器中运行。 [iOS 模拟器构建](https://docs.codemagic.io/yaml-code-signing/ios-simulator-builds/)

## 安装到自己的 iPhone

在 Codemagic 手动启动 **NxtRep Native iPhone Unsigned IPA**（`native-ios-device`）工作流，选中 `codex/ios-native-preview` 分支。该工作流检查 1024×1024 不透明图标，再使用 Release 配置编译 iPhone 真机版本。打包前会校验 `Info.plist`、arm64 可执行文件和编译后的图标资源。构建成功后下载 `NxtRepNative-unsigned.ipa`，使用本地 AltServer / AltStore Classic 以自己的 Apple 账户重新签名安装。

1. 在 Windows 按 AltStore 官方安装指南配置 AltServer，以及指南要求的 iTunes 和 iCloud 组件。
2. 使用 USB 连接并解锁 iPhone，在手机上信任这台电脑。通过 AltServer 托盘菜单的 **Install AltStore** 选择该 iPhone，按提示在本机输入自己的 Apple 账户。
3. 在 iPhone 的设置中信任该开发者账户，并在 **隐私与安全性 → 开发者模式** 启用开发者模式，按手机提示重启。
4. 将下载的 IPA 保存到 iPhone 的“文件”中，通过 AltStore Classic 导入安装。首次打开 NxtRep 后检查桌面图标、首页布局、页面切换和训练计时。

Windows 安装组件、设备信任和开发者模式的具体操作以 AltStore 官方指南为准。 [AltStore Windows 安装指南](https://faq.altstore.io/altstore-classic/how-to-install-altstore-windows)

免费 Apple 账户可用于个人设备开发签名。签名的有效期为 7 天，设备同时可安装最多 3 个此类 App。需要在到期前通过能连接 AltServer 的 AltStore 刷新签名，AltStore 自身也占用一个 App 名额。 [Apple 个人开发账户限制](https://developer.apple.com/help/account/basics/about-your-developer-account) · [AltStore 刷新与应用名额](https://faq.altstore.io/altstore-classic/your-altstore) · [连接 AltServer](https://faq.altstore.io/altstore-classic/altserver)

每次变更后仍需以实际构建结果确认 IPA 可生成，并在个人 iPhone 上完成重新签名、安装及运行验收。原有 0.1.0 预览已完成首次真机启动；0.2.0 的接口联调验收需使用新安装包单独确认。

## 在 Mac 上查看界面

在 Xcode 16 或更新版本中打开 `ios-native/NxtRepNative.xcodeproj`，选择 `NxtRepNative` scheme 和 iPhone 16 模拟器，点击 Run。若已有 Codemagic 构建包，也可以解压后在启动了 iPhone 16 模拟器的 Mac 上，从解压目录执行以下命令。

```bash
xcrun simctl install booted NxtRepNative.app
xcrun simctl launch booted com.zengsiqi.nxtrep.native
```
