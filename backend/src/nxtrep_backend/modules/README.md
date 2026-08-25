# 业务模块落位

后续按垂直业务拆分，每个模块内部可包含 `models.py`、`schemas.py`、`repository.py`、`service.py`：

- `accounts`：预创建账号、密码、用户隔离。
- `profiles`：目标、器械、伤病、饮食限制、通知授权。
- `training`：动作库、计划与版本、日历、训练快照、组记录、PR。
- `nutrition`：食物来源、营养快照、餐食、目标范围、自由餐。
- `progress`：身体测量、体脂方法、平滑趋势、周报。
- `agent`：会话、会话摘要、确认草稿、Memory、工具审计。
- `sync`：客户端幂等键、游标、冲突版本和 tombstone。

不要先建立一个跨所有业务的巨大 `models.py`；先完成 MVP-0 的纵向闭环，再增加模块。

