# 废弃代码与临时产物清理

日期：2026-11-03（Asia/Shanghai）。范围为当前工作区中的无调用旧实现、一次性诊断脚本和历史调试产物。保留原有未提交工作；没有提交、推送或部署。

## 源码清理

已核对生产代码、正式测试、启动脚本与文档中的引用，移除以下旧实现：

- 早期内存版确认流程：`ConfirmationService`、内存仓库、旧确认 Schema 和 `domain/confirmation.py`。现行数据库确认服务、事务执行、版本检查及公开接口继续保留。旧实现移除后，删除了只剩空入口的 `domain` 包。
- 已被现行语义路由替代的三个函数：`is_explicit_training_plan_creation_request`、`_is_high_confidence_knowledge_query`、`explicit_meal_date_change`。
- 仅测试上述废弃函数的三个测试定义，共 8 个参数化用例。现行语义路由、改期、确认安全和数据库回归测试全部保留。
- 无引用的旧页面对比图 `frontend/nxtrep-before.png`。

源码与旧测试合计减少 374 行。根 `.gitignore` 补充 Python 字节码和 Ruff 缓存规则，避免生成文件进入待提交列表。

## 临时产物清理

| 类别 | 已删除目标数（目录或文件） |
| --- | ---: |
| 一次性诊断、改码脚本和代码片段 | 36 |
| 无引用的历史源码快照 | 19 |
| 旧 pytest 临时工作目录 | 86 |
| 逐帧页面录制目录 | 3 |
| 旧截图、UI dump、日志、安装包及工具临时文件 | 226 |
| Python 字节码缓存目录 | 40 |
| 可重建的工具缓存目录 | 2 |
| 旧页面对比图 | 1 |

以上旧产物共 **6,689 个文件，335,070,909 字节，约 319.55 MiB**。数字按删除前文件大小累加，不代表磁盘可用空间的精确增量；不包含两个废弃源码文件的删除，也不把本次验收新生成后又清掉的工作目录算作旧产物。

清理逐项核对绝对路径位于本仓库内，检查目录链接和当前进程引用，再使用 PowerShell 删除。保留了：

- 正式测试、迁移、部署与启动脚本、验收记录和文档引用的证据。
- `.env`、数据库目录、加密测试账号、当前 API 状态与日志、正常 App APK 缓存，以及开发依赖和构建环境。
- 文档和本地样本配置仍引用的图片及配置，`output/resume` 个人交付文件，以及 PDF 目录。
- 4 份数据库日志和 1 个 JVM 运行目录，避免影响本机运行环境。

另有 **17 个历史缓存目录无法安全枚举**，记录在清单中并保留，没有修改其 ACL 或强行穿过链接。其中 `backend/.pytest_cache` 在本次测试结束时产生一条缓存写入权限警告；不影响测试结果。本次验收自己的 `pytest-current` 临时目录已清除，日志和 XML 结果保留。运行工具后正常再生成的缓存不属于废弃源码。

## 验证

| 检查 | 结果 |
| --- | --- |
| 后端全量，显式启用 PostgreSQL 集成测试 | **2146 passed, 65 skipped**，78.91 秒；1 条旧缓存权限警告 |
| Ruff，后端源码与测试 | 通过 |
| 重启前后完整 OpenAPI 比较 | 完全相同，178 个路径 |
| 本地 API 启动与就绪检查 | 启动脚本完成后端重启，`health/ready` 为 `ready` |
| 运行 API 源码指纹 | 与清理后的当前源码一致 |

上次全量为 2154 项通过，本次减少的 8 项正好对应已移除旧函数的专属用例，没有通过跳过现行业务用例来减少失败。本轮没有修改 Flutter 业务代码，没有重跑外部模型或设备流程；此前 AI 真实接口和 Android 复验结果见 [AI 修复与复验记录](AI_MULTITURN_RELIABILITY_FIX.md)。

## 本地记录

记录目录为 `.local/maintenance/cleanup-20261103/`，不纳入 Git：

- `source-paths-before.zip`：本轮涉及源码、旧测试和忽略规则的清理前副本，保留相对路径。
- `source-changes.patch`、`source-changes.json`：相对于本轮开始时的精确差异，不与原有未提交改动混算。
- `inventory.json`、`plan.json`、`deletion-results.json`、`extra-deletions.json`：候选、引用保护、删除结果与保留原因。
- `backend.log`、`backend.xml`、`ruff.log`、`api-restart.log`、`validation.json`：验证日志与结果。
- `openapi-before.json`、`openapi-after.json`：接口契约比较依据。

源码副本用于核对或按需恢复单个文件；旧临时截图、缓存与一次性脚本没有另建全量副本。
