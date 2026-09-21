# NxtRep 前端设计 QA

## 参考来源

- `C:\Users\Zeng siqi\Documents\xwechat_files\wxid_k6qismaajpat22_0ca0\temp\RWTemp\2026-09\9e20f478899dc29eb19741386f9343c8\3b10d2112569fdff79efdeb77c454376.jpg`
- `C:\Users\Zeng siqi\Documents\xwechat_files\wxid_k6qismaajpat22_0ca0\temp\RWTemp\2026-09\9e20f478899dc29eb19741386f9343c8\1a8900e7742cd5ea0035c43c9660c2d5.jpg`
- `C:\Users\Zeng siqi\Documents\xwechat_files\wxid_k6qismaajpat22_0ca0\temp\RWTemp\2026-09\9e20f478899dc29eb19741386f9343c8\ce8e5cb4362e136d562376d3e22db1b2.jpg`
- `C:\Users\Zeng siqi\Documents\xwechat_files\wxid_k6qismaajpat22_0ca0\temp\RWTemp\2026-09\9e20f478899dc29eb19741386f9343c8\7d1fa2fda34e0135839b8407c4485ddc.jpg`

参考图尺寸均为 1179 x 2556。它们只作为布局、层级、颜色和交互密度参考，没有复制品牌、人物照片、社区、同城或挑战功能。

## 实现证据

模拟器：Pixel 8 Android Emulator，截图尺寸 1080 x 2400。

- `artifacts/screenshots/nxtrep-home.png`：已登录、恢复日首页。
- `artifacts/screenshots/nxtrep-plan.png`：无启用计划、无当日安排。
- `artifacts/screenshots/nxtrep-progress.png`：无身体记录。
- `artifacts/screenshots/nxtrep-after-current.png`：AI 教练欢迎页。
- `artifacts/screenshots/nxtrep-profile.png`：账户页。
- `artifacts/screenshots/nxtrep-stream-fast/frame-16.png` 至 `frame-19.png`：同一回答连续增量显示及完成状态。
- `artifacts/screenshots/nxtrep-home-font-130.png`：登录页在系统字体 1.3 倍下的显示检查。
- `artifacts/screenshots/reference-vs-plan.png`：参考计划页与实现页并排对照。

## 对照历史

### 第 1 轮

- 问题：默认 Material 绿色主题、重复的 AppBar/Card/ListTile 结构、页面层级弱，AI 助手使用大块灰色气泡且原始 Markdown 可见。
- 调整：建立明确的浅灰画布、白色圆角卡、深色摘要卡、珊瑚红主操作、统一大标题与五栏导航。

### 第 2 轮

- 问题：首次 AI 发送要等会话创建后才出现消息；流式期间每个增量都触发滚动动画；常用“今天怎么练”仍经过慢速意图模型。
- 调整：先插入用户消息和助手占位，滚动改为靠近底部时节流跟随；常用问题使用本地快速路由，助手正文按真实 SSE 增量更新。

### 第 3 轮

- 问题：AI 同一轮并发调用多个工具时共用 AsyncSession，训练数据查询会失败。
- 调整：请求内工具和业务分支增加会话级串行保护，并为“今日训练”提供直接读取业务服务的快速路径。

## 最终检查

- 主页面在 1080 x 2400 下无横向溢出、底栏遮挡或不可见主操作。
- 登录页在 1.3 倍系统字体下无文字截断或控件重叠，测试后已恢复为 1.0。
- 首页、计划、进展、AI 教练和我的页面均保留真实可执行入口及原有 API 契约。
- 首次训练方式只有“徒手训练”和“健身房器械训练”，提交值仍映射为后端现有器械代码。
- AI 回复实际观察到多帧内容递增，完成前显示流式光标，完成后恢复可发送状态。
- 代码未引用 `Image.asset`、`AssetImage`、`DecorationImage` 或任何生成图片；真实图片留待后续接入。

## 结果

passed
