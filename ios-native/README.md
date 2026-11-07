# NxtRep 原生 iOS 预览

SwiftUI 预览面向 iOS 18 及以上版本的 iPhone。使用内置演示数据，可体验首页营养和饮水圆环、饮水记录、训练和其他功能入口。预览可以离线运行，业务数据目前由本地演示状态提供。

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

此真机工作流的配置完成后，仍需以 Codemagic 的实际构建结果确认 IPA 可生成，并在个人 iPhone 上完成重新签名、安装及运行验收。原生前端目前使用本地演示数据。

## 在 Mac 上查看界面

在 Xcode 16 或更新版本中打开 `ios-native/NxtRepNative.xcodeproj`，选择 `NxtRepNative` scheme 和 iPhone 16 模拟器，点击 Run。若已有 Codemagic 构建包，也可以解压后在启动了 iPhone 16 模拟器的 Mac 上，从解压目录执行以下命令。

```bash
xcrun simctl install booted NxtRepNative.app
xcrun simctl launch booted com.zengsiqi.nxtrep.native
```
