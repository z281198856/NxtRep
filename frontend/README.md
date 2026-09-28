# NxtRep 移动端

Flutter 前端对接仓库中的移动端契约与后端 OpenAPI。当前已完成登录与令牌轮换、首次四问设置、训练日历和训练记录闭环、饮食独立导航与餐食照片 AI 估算、身体测量与围度体脂估算、AI 教练 POST SSE 与照片上传，以及固定六栏主导航。餐食照片识别的营养值需用户核对后保存；体脂估算不等同于设备实测。

## 本地运行

先确认配置的本机 PostgreSQL 已启动；后端 `/health` 只表示服务进程存活，数据库未启动时登录仍会失败。

1. 在仓库根目录启动后端：

   ```powershell
   cd backend
   $env:PYTHONPATH="src"
   .\.venv\Scripts\python.exe -m uvicorn nxtrep_backend.main:app --host 0.0.0.0 --port 8000
   ```

2. 启动 Android Studio 的 Pixel 8 模拟器。
3. 用 VS Code 打开 `frontend` 文件夹。
4. 在状态栏设备选择器中确认设备是 Pixel 8 / `emulator-5554`。
5. 打开“运行和调试”，选择 `NxtRep - Pixel 8`，按 F5。

Android 模拟器通过 `http://10.0.2.2:8000/api/v1` 访问 Windows 上的后端。这个 HTTP 地址只允许 Debug 构建使用；发布版应通过以下参数指定 HTTPS API：

```powershell
flutter build apk --dart-define=API_BASE_URL=https://api.example.com/api/v1
```

Android 模拟器只用于当前 Windows 本机功能测试；iOS 构建仍需在云 Mac 上完成。如果 Windows 构建在 Gradle 启动阶段报 `Unable to establish loopback connection`，可在当前 PowerShell 会话中给 JDK 指定一个现有、可写且路径较短的临时目录后重试；本机验证可用的示例：

```powershell
$env:JAVA_TOOL_OPTIONS='-Djdk.net.unixdomain.tmpdir=C:\Windows\Temp'
flutter build apk --debug
```

## 检查

```powershell
flutter analyze
flutter test
```

设备端只读回归覆盖独立测试账号登录、当前计划详情、训练计划目录、食品库与动作库。测试账号须已完成首次设置并启用至少一天含动作的计划。先确保本机数据库、后端和 Android 模拟器运行，再在 `frontend/tmp/e2e.local.json` 放入仅供本地测试的账号（`tmp` 已被 Git 忽略）：

```json
{"E2E_USERNAME":"本地测试用户名","E2E_PASSWORD":"本地测试密码"}
```

从 `frontend` 目录执行：

```powershell
flutter test integration_test/local_read_only_smoke_test.dart -d emulator-5554 --dart-define-from-file=tmp/e2e.local.json
```

不要使用正式用户账号；该测试只读取数据，不创建训练或饮食记录。测试结束后可删除本地凭据文件。

另有 AI 设备端用例，会请求模型生成待确认的训练计划草稿，不会自动启用。它使用合成测试资料：身高 173 cm、最近体重 70 kg、体脂 18%，且需要后端模型已配置。只对专用测试账号运行：

```powershell
flutter test integration_test/local_ai_plan_smoke_test.dart -d emulator-5554 --dart-define-from-file=tmp/e2e.local.json
```

## 代码结构

- `lib/core`：环境配置、统一 API 客户端、SSE、安全令牌存储。
- `lib/features/auth`：登录、首次密码设置、会话恢复。
- `lib/features/onboarding`：目标、频率、器械、伤病四步初始化。
- `lib/features/training`：计划、日历、训练和组记录。
- `lib/features/nutrition`：独立饮食页、食品库、餐食照片估算和用户确认记录。
- `lib/features/progress`：身体测量、围度体脂估算与进展趋势。
- `lib/features/agent`：可恢复的 AI 教练流式会话、照片输入与确认卡。
- `lib/core/media`：按后端能力限制转换、压缩并直传用户主动选择的图片。

刷新令牌只保存在 Android Keystore / iOS Keychain 封装的安全存储中，访问令牌只驻留内存。不要在日志或截图中暴露令牌。
