# NxtRep 原生 iOS 预览

SwiftUI 预览面向 iOS 18 及以上版本的 iPhone。使用内置演示数据，可体验首页营养和饮水圆环、饮水记录、训练和其他功能入口。预览可以离线运行，业务数据目前由本地演示状态提供。

## 在 Codemagic 编译

1. 将包含 `ios-native/` 和根目录 `codemagic.yaml` 的分支推送到 GitHub。
2. 在 Codemagic 个人工作区添加该 GitHub 仓库，使用 `codemagic.yaml` 配置。若工作流尚未识别，选中该分支后点击 **Check for configuration file**。
3. 点击 **Start new build**，选中该分支和 **NxtRep Native iOS Simulator**（`native-ios-simulator`），点击 **Start new build**。
4. 构建成功后，在 **Artifacts** 下载 `NxtRepNative-simulator.zip`。附加产物压缩包中包含原生首页截图 `NxtRepNative-home.png` 和编译日志 `xcodebuild.log`，可在 Windows 上查看。

工作流使用 Mac mini M2 和 Xcode 26.0 镜像，在预装的 iPhone 16（iOS 18.5）模拟器中启动 App 并截图。编译或截图失败时，构建详情会标出失败步骤。此流程可使用个人账户的 M2 免费构建额度，截图也在同一次构建中生成。 [Codemagic 镜像规格](https://docs.codemagic.io/specs-macos/xcode-26-0/) · [YAML 工作流](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/) · [构建额度](https://docs.codemagic.io/billing/pricing/)

模拟器编译无需 Apple Developer 会员或签名证书。产物解压后是 `NxtRepNative.app`，可在兼容的 macOS iOS 模拟器中运行。真机安装需要单独构建并签名。 [iOS 模拟器构建](https://docs.codemagic.io/yaml-code-signing/ios-simulator-builds/)

## 在 Mac 上查看界面

在 Xcode 16 或更新版本中打开 `ios-native/NxtRepNative.xcodeproj`，选择 `NxtRepNative` scheme 和 iPhone 16 模拟器，点击 Run。若已有 Codemagic 构建包，也可以解压后在启动了 iPhone 16 模拟器的 Mac 上，从解压目录执行以下命令。

```bash
xcrun simctl install booted NxtRepNative.app
xcrun simctl launch booted com.zengsiqi.nxtrep.native
```
