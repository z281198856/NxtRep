# NxtRep 移动端

Flutter 前端严格对接仓库中的移动端契约与后端 OpenAPI。当前已完成登录与令牌轮换、首次四问设置、训练日历和训练记录闭环、今日饮食、身体测量、AI 教练 POST SSE 与照片上传，以及固定五栏主导航。

## 本地运行

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

## 检查

```powershell
flutter analyze
flutter test
```

## 代码结构

- `lib/core`：环境配置、统一 API 客户端、SSE、安全令牌存储。
- `lib/features/auth`：登录、首次密码设置、会话恢复。
- `lib/features/onboarding`：目标、频率、器械、伤病四步初始化。
- `lib/features/training`：计划、日历、训练和组记录。
- `lib/features/nutrition`：每日汇总和手动饮食记录。
- `lib/features/progress`：身体测量与进展。
- `lib/features/agent`：可恢复的 AI 教练流式会话、照片输入与确认卡。
- `lib/core/media`：按后端能力限制转换、压缩并直传用户主动选择的图片。

刷新令牌只保存在 Android Keystore / iOS Keychain 封装的安全存储中，访问令牌只驻留内存。不要在日志或截图中暴露令牌。
