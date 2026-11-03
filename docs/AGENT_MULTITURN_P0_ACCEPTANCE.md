# 多轮 Agent 第一批 P0 验收

日期：2026-10-08。对应[完整审计和分阶段方案](AGENT_MULTITURN_PRODUCTION_AUDIT.md)。本批只补现有调用链的工具执行安全、失败草稿恢复和同会话并发，不重写 Agent，也不引入 Redis、Task Manager 或新框架。

## 实际修改范围

- `agents/tools/context.py` 增加同一次运行共享的 `AgentToolJournal`；`dataclasses.replace` 和重新构建工具仍共享同一对象。
- `agents/tools/registry.py` 在原串行 wrapper 中识别副作用、计算完整参数指纹、复用同轮成功结果、保护未知结果、检查最小结果结构，并限制工具总调用和无进展重复。
- `agents/tools/journal.py` 是小辅助层，不是新的业务 Tool 系统。只读工具继续读取实时数据；参数变化不当作旧操作。PATCH 的字段存在性参与指纹，省略与显式清空不能混淆。
- `agents/tools/nutrition.py` 修正自定义食品旧局部缓存遗漏完整营养参数、修改 patch 的问题，保留原 Service。
- `services/agent_run.py` 和原 repository 使用短事务行锁检查会话占用、原子结算运行、拒绝旧运行迟到写入。默认超过 600 秒且已超过配置执行预算的运行可在下一次请求时结算为中断；不会自动重跑工具。
- `services/agent_workflow.py` 在节点/成功/失败/取消/断流时保存最小 journal；专用业务分支也从 execution_bundle 收集真实卡 ID。
- 原 conversation 恢复查询兼容最终 response 和新 checkpoint 引用，从数据库校验所属账号、记录存在、当前状态和替换链。
- 原 `ConversationService` 在保存消息前检查占用，保存助手消息前重新锁定并刷新会话序号；factory 接入原 run service 和 journal。
- 普通 chat 请求被占用时返回 HTTP 409 / `AGENT_CONVERSATION_BUSY`；SSE 沿用原 failed 事件并显示同一准确中文原因。

确认批准 API、业务数据模型、业务 Service、四节点 Graph、前端确认卡交互均保留。没有数据库迁移、云部署、真实 iOS 验收或提交/推送。

## 自动化验收与证据

以下测试使用固定故障注入，数据库测试使用独立临时 UUID 用户并清理；不调用真实模型。

| 场景 | 必须满足的结果 | 测试位置 |
| --- | --- | --- |
| 同轮及跨 builder 重复 proposal | 一个真实 Confirmation；批准前 0 条正式饮食，批准后 1 条 | `test_agent_tool_gateway.py`、`test_agent_gateway_database.py` |
| 参数纠正 / PATCH 空值 | 新参数不能返回旧卡；省略 brand 与清空 brand 的指纹不同 | `test_agent_tool_gateway.py`、食品工具测试 |
| 草稿取消或被修订替换后重放旧参数 | 返回失效/需核实，不能把旧 pending 卡伪装成有效卡，也不能再次写入 | `test_agent_tool_gateway.py` |
| Tool 超时或未知结果 | 同轮相同动作不得盲目重新执行；确定的参数/业务失败与未知结果区分 | `test_agent_tool_gateway.py` |
| 副作用结果格式不完整 | 不返回成功，不重复写；有真实 UUID 时仍交给恢复查询核实 | `test_agent_tool_gateway.py` |
| 相同查询无进展 / 工具总预算 | 有限调用后明确停止；读取结果真实变化不能被旧缓存遮住 | `test_agent_tool_gateway.py` |
| Tool 成功后回复失败 | run 仍失败；真实待确认卡可恢复；不生成正式饮食或成功回复 | `test_agent_gateway_database.py` |
| checkpoint 已提交后再超时 | 已存在草稿保留并可恢复；不能假称所有写入已回滚 | `test_agent_gateway_database.py` |
| 未提交修订超时 | 未提交卡及修订回滚，旧卡状态不变；不存在引用不得恢复 | `test_agent_timeout_database.py`、`test_agent_run_journal_database.py` |
| 两个请求/数据库 session 同会话并发 | 第二个请求在追加消息或调用模型之前被拒绝 | `test_agent_turn_safety.py` |
| 旧 run 已终结却迟到返回 | 四种结算路径均不复活 run、不提交迟到业务写入 | `test_agent_run_journal_database.py` |
| 跨 session 结算竞争 | 校验与提交同一短事务，超龄接管不能穿透正在进行的结算 | `test_agent_run_journal_database.py` |
| 归属/替换/状态恢复 | 过滤其他用户、不存在卡；使用当前状态，仅恢复当前有效卡 | `test_conversation_confirmation_recovery.py` |
| 另一个写入者更新消息序号 | 助手回复刷新序号，不能复用旧 identity map 导致冲突 | `test_agent_turn_safety.py` |

完整后端回归：`RUN_DATABASE_TESTS=1`，**1349 passed / 27 skipped，23.61 秒**。27 项跳过未计为通过。本批统一运行的日志为 `.local/agent-p0-full-tests-20261008.log`；先前的定向 15 / 56 / 95 项及真实 gateway 数据库 3 项包含在完整回归中，不应将它们相加当成更多通过测试。

所改源码及测试的 Ruff 检查、对应 `git diff --check` 均通过。真实数据库故障注入已验证；真实模型在新代码上的多轮验收、Android 模拟器操作和真实 iOS 本轮尚未验证。审计阶段读取旧测试不算本批通过。

本地后端已通过原手动入口重载：`GET /api/v1/health/ready` 返回 `{"status":"ready"}`，OpenAPI仍包含原 chat、conversation SSE和run查询入口。PostgreSQL为 Running / Manual；后端按需启动，未启动提醒worker、未设自启动。重载前的API日志已在`.local/agent-p0-api-before-*.log`备份。以上只证明本地接口就绪，不能替代真实模型或设备验收。

## App 中如何验收

本批只改后端。正常本地入口可按需加载新后端：在项目目录运行 `Start-NxtRep.cmd -RestartBackend`；只启动后端可使用 `scripts/Start-Local.ps1 -BackendOnly -RestartBackend`。这些入口不会配置开机自启动，也不会自动启动提醒 worker。

1. 在 AI 页面新建一个测试会话，输入“帮我记录今天午饭，熟米饭 200 克、鸡胸肉 150 克，先生成草稿”。应出现待确认卡，批准前饮食页不得新增正式记录。
2. 暂不批准，离开 AI 页面后从历史重新打开同一会话。应恢复一张有效草稿，份量一致；不是依赖旧回复文字猜状态。
3. 批准一次，检查饮食页只新增一条记录。重新进入会话，已生效卡不能重新显示成 pending。
4. 对另一张未批准草稿明确说“取消刚才这份草稿”。核对卡的实际取消状态，重新打开历史也不应重新出现为有效待确认卡。
5. 若有两个客户端，可在同一会话第一条仍处理中时发送第二条。第二条应明确提示上一条仍在处理；不插入第二次业务执行。

模型是否提出重复 Tool Call 不能靠连续点击人工稳定复现；同轮去重、格式错误、超时、断流和结算竞争以固定故障注入测试为依据。本轮尚未把上述操作计为 Android 模拟器通过，真实 iOS 仍未验收。

## 本批明确边界与下一步

- 同轮 journal 不是跨 HTTP 请求、跨会话或跨重启的任务幂等。运行占用检查挡住并发；上一轮已经结束后，手动重复发送仍可能开启新运行。下一批要补稳定客户端 turn 身份及结果重放。
- 当前没有持久结构化 Task State；“8个”等补参、连续纠正、多候选指代、任务暂停/恢复、新动作数值清空仍按审计计划补强。没有把这些案例认定为已通过。
- run checkpoint 现在保留执行结果引用，仍不是任意步骤续跑的 graph checkpoint。进程在 Tool 返回/引用落库前硬退出的极小窗口仍需后续持久 Action 身份解决；不得无依据猜关联或自动重复写。
- 工具 budget 为每次运行最多 64 次实际处理，无进展相同调用默认最多 3 次；原 32 步递归限制和图执行 timeout 继续保留。成功副作用、同查询实际结果变化可更新进展；查询时间等非业务字段不算进展。schema 在进入网关前拒绝的调用不计入 64 次，仍受图步骤限制；摘要仍在主图超时之外，独立预算列为后续 P1。
- 日志与 checkpoint 只存内部 gateway 调用 ID、参数指纹、状态、耗时和结果引用，没有打印用户原话、完整参数、密钥或令牌。这里的 gateway 调用 ID尚不等于原模型 Tool Call ID；task/turn 关联与完整受控 Trace 待补。
- 已保存餐食目前支持克数修订和删除，不支持直接覆盖营养快照。“脂肪应该多一点”这类自然反馈的澄清与能力边界处理仍是 P1，详见审计中的真实失败记录。
