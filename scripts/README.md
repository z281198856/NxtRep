# Windows 本地按需启动

这些脚本只用于本机开发，不是服务器部署方案。不会创建开机启动项、计划任务，也不启动主动教练 worker。

## 日常使用

在仓库根目录双击 `Start-NxtRep.cmd`：检查 PostgreSQL、确认数据库迁移、启动 API、打开 Android 模拟器、安装正常 App。未登录时使用专用本地测试账号登录；已有登录会话则保留。用完双击 `Stop-NxtRep.cmd`，停止此入口启动的 API、数据库和模拟器，保留数据库文件与 App 数据。

启动前已经运行的数据库或模拟器默认不关闭。如明确要关闭它们，执行 `Stop-NxtRep.cmd -Database -Emulator`。端口被不属于本脚本的 API 占用时会报错，不会强杀其他进程。

前提：Windows PowerShell 5.1+，PATH 中有 `flutter` 和 `adb`，Android SDK 中已有 `Pixel_8` AVD；已安装 `postgresql-x64-17` 服务及 pgvector，完成后端依赖安装、`.env` 和数据库迁移。其他机器需调整服务名或创建对应 AVD，不会自动安装工具链。

```powershell
# 第一次配置权限：从自己的普通账号运行，只在此时弹出一次 UAC
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Enable-LocalDatabase.ps1

# 只启动数据库与后端
.\Start-NxtRep.cmd -BackendOnly

# iPhone 联调，显式允许 API 监听网络接口（已有 API 时加 -RestartBackend）
.\Start-NxtRep.cmd -BackendOnly -Lan

# 后端源码或 .env 变化后显式重启
.\Start-NxtRep.cmd -RestartBackend

# 强制重建正常 App，或选择已连接的模拟器
.\Start-NxtRep.cmd -Rebuild
.\Start-NxtRep.cmd -Device emulator-5554
```

权限配置保留 PostgreSQL 的“手动”启动方式，仅向当前 Windows 用户授予这个服务的启动、停止权限；不授予修改服务配置权限，不修改数据库目录权限。原服务 ACL 备份在 `.local/postgresql-service-acl-before.json`。此权限适合个人开发机；如果 PostgreSQL 同时供其他项目使用，停止前先确认其他项目不需要它。

## 固定环境与账号

- 数据库严格使用 `backend/.env` 的 `NXTREP_DATABASE_URL`，仅接受本地环境、回环地址、5432 端口。不切换临时数据库；环境变量覆盖了不同数据库时拒绝启动。原有用户与业务记录不会被重置。
- API 默认使用 `127.0.0.1:8000`，通过 `/api/v1/health/ready` 验证数据库连接。Android 模拟器访问 `10.0.2.2:8000`。个人 iPhone 联调可显式加 `-Lan` 切换为 `0.0.0.0:8000`，再按 `ios-native/README.md` 限定 USB 防火墙访问；该入口不用于生产部署。
- 正常入口 APK 缓存在 `.local/nxtrep-main-debug.apk`，根据源码摘要按需构建，不复用集成测试生成的 APK。安装使用 `-r`，不清空 App 数据。SDK 升级或手动改变外部构建环境后使用 `-Rebuild`。
- 首次生成非管理员专用测试账号及合成基础资料，之后复用，不自动重置密码。训练计划和历史记录仍需在 App 内设置，不代表具备所有集成测试的预置数据。
- 账号通过 Windows DPAPI 加密保存在 `.local/test-account.xml`，只能由同一台电脑的同一 Windows 用户解密；旁边的数据库标识防止误用到其他库。整个 `.local/` 被 Git 忽略，不应上传或分享。

需要手动输入账号时，在自己的终端查看（不要截图或粘贴输出到公开日志）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Local-TestAccount.ps1 -Show
```

启动失败时首先检查终端提示和 `.local/api.err.log`；脚本会保留已启动资源以便诊断，可以运行停止入口清理。关闭启动窗口本身不会停止后台服务；请使用 `Stop-NxtRep.cmd`。

## 持续质量检查

在项目根目录执行 `backend/.venv/Scripts/python.exe scripts/verify_quality.py`，运行固定 AI / 视觉回归、Flutter 测试和静态检查。可添加 `--database` 做临时账户的数据库回归，添加 `--live --repeats 2` 调用已配置的真实模型。`--samples <manifest.json>` 只在 `--live` 下上传明确提供的餐图；真实餐图样例和称重要求见 [验收说明](../docs/OFFLINE_AND_QUALITY_ACCEPTANCE.md)。

每轮报告在 `.local/quality-runs/` 的独立目录，失败返回非零退出码。`--baseline <report.json>` 对比前次失败项。没有指定真实样本时，报告会把份量、热量准确率记为未测量。此脚本按调用执行，没有后台定时任务。

Android 持久恢复验收使用 `--no-uninstall` 保留应用数据，先核实安装仍存在，再停止进程并启动下一阶段。`RUN_OFFLINE_DEVICE_TESTS=1` 对应后端 `tests/test_offline_recovery_device.py`；需从后端目录执行，以读取本地配置。
