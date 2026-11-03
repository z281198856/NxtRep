# NxtRep 移动端

Flutter 前端对接仓库中的移动端契约与后端 OpenAPI。当前已完成登录与令牌轮换、首次四问设置、训练日历和训练记录闭环、饮食独立导航与餐食照片 AI 估算、身体测量与围度体脂估算、AI 教练 POST SSE 与照片上传，以及固定六栏主导航。餐食照片识别的营养值需用户核对后保存；体脂估算不等同于设备实测。

“我的 → 账户安全”支持修改密码、查看当前及其他登录设备、逐台退出和退出其他所有设备。
修改密码成功后更新本机登录状态并退出旧登录；被远程退出后关闭已打开的受保护页面，返回登录页。
密码修改结果不明确时不会自动重复提交，改为提示重新登录核对。详见[账户安全验收](../docs/ACCOUNT_SECURITY_ACCEPTANCE.md)。

“我的 → 手机系统提醒”支持训练、三餐、饮水、体重体脂的本机定时通知，默认关闭，支持星期/时间、免打扰、隐藏内容和测试通知。实现原理、系统限制与手机验收步骤见[本机提醒验收](../docs/LOCAL_REMINDERS_ACCEPTANCE.md)。

## 本地运行

已配置的 Windows 本机优先使用仓库根目录的 `Start-NxtRep.cmd` / `Stop-NxtRep.cmd`：按需启停数据库、后端和模拟器，复用专用测试账号与未变化的正常 APK，不开机自启动。权限设置及限制见 [Windows 启停说明](../scripts/README.md)。以下为手动调试步骤。

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

写入型设备回归会在测试账号下新增一条饮食记录，同时验证拍照入口、进展与个人资料页。只应对隔离数据库中的专用账号运行：

```powershell
flutter test integration_test/local_core_write_smoke_test.dart -d emulator-5554 --dart-define-from-file=tmp/e2e.local.json
```

## 代码结构

饮食页在三大营养素下方提供早餐、午餐、晚餐和记饮水四个并排入口；餐次入口会预选对应餐次。饮水支持 150 / 250 / 500 ml 快选、自定义 1–5000 ml、当天累计和删除误记，独立存储，不计入热量及餐食完整度。进展页通过“＋ 记体重 / 体脂”进入现有测量表单。

营养目标按上下限区间展示，三餐覆盖按不同主餐类型计算；重复早餐、加餐不会充当午晚餐。
切换到过去日期可补记餐食、照片和饮水，“补记昨天”可一键切换；录入界面明确显示目标日期。
“复制上一餐”可选择最近的餐食，核对份量、日期和餐次后保存。AI 可记录明确毫升数的饮水，
先生成独立饮水确认卡，确认后才计入相应日期，也可查询历史饮水或修订尚未确认的容量。

- `lib/core`：环境配置、统一 API 客户端、SSE、安全令牌存储。
- `lib/features/auth`：登录、首次密码设置、会话恢复。
- `lib/features/onboarding`：目标、频率、器械、伤病四步初始化。
- `lib/features/training`：计划、日历、训练和组记录。
- `lib/features/nutrition`：独立饮食页、食品库、餐食照片估算和用户确认记录。
- `lib/features/progress`：身体测量、围度体脂估算与进展趋势。
- `lib/features/agent`：可恢复的 AI 教练流式会话、照片输入与确认卡。
- `lib/core/media`：按后端能力限制转换、压缩并直传用户主动选择的图片。

刷新令牌只保存在 Android Keystore / iOS Keychain 封装的安全存储中，访问令牌只驻留内存。不要在日志或截图中暴露令牌。

## 离线记录与草稿（2026-11-02）

「我的 → 离线记录与草稿」管理待同步记录，主页面离线提示也可进入。手动饮食、饮水、身体测量和已开始训练的记组会先保存在本机；已核对的餐食照片可在本机排队保存。草稿列表支持继续填写，照片和识别预览恢复后仍需用户主动识别或确认。

离线启动使用该账户的本机缓存，联网后核实登录并同步。新训练、结束训练、旧记录修改/删除和 AI 确认仍需联网；冲突和超过安全重试时间的记录保留待核对。详细范围和证据见 [离线与质量验收](../docs/OFFLINE_AND_QUALITY_ACCEPTANCE.md)。
