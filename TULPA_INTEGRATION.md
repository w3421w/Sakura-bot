# Tulpa 与 QWbot 整合评估

## 结论

Tulpa 已拉取到 `third_party\\Tulpa`，当前固定到浅克隆提交 `0090b27`。它和 QWbot 的 OneBot/NapCat 方向高度相关，但两者定位不同：Tulpa 是带授权边界的 QQ/微信资料访问、MCP 工具和持续聊天侧车；QWbot 是直接消费 OneBot 事件、调用 DeepSeek API 并自动回复的机器人。

不建议把 Tulpa 整个项目复制进 QWbot，也不建议让两个程序同时成为同一条消息的自动回复器。

## 可以复用的设计

1. OneBot 事件接收：Tulpa 有心跳、账号核对、重连、事件超时和连接状态管理。
2. 写操作安全：Tulpa 对发送/群管理使用授权范围、目标校验、幂等键和 UNKNOWN 回执，不盲目重试。
3. 会话边界：按账号、群/好友会话、授权范围隔离实时消息。
4. 人格目录：人格使用 Markdown 文件动态发现，并在会话启动时保存人格快照。
5. 学习与证据：学习候选与最终可见记忆分开，保留消息来源和可追溯信息。
6. 媒体与引用：支持引用消息、原生 @、图片/文件按需读取，且有权限分层。

## 不应直接搬入的部分

- Tulpa 不负责内置模型回复；MCP 轻量版要求外部 Agent 调用工具。
- Tulpa 的 SQLite 结构是 MCP 授权、会话和事件缓存模型，不能直接替换 QWbot 的聊天记忆/RAG 数据库。
- Tulpa 的 WebSocket 接收器与 QWbot 都会消费 OneBot 事件；直接并行接入可能造成重复事件处理或重复发送。
- Tulpa 依赖独立的 `.env`、MCP 服务和较重的可选组件，不应把其 Token、DeepSeek 配置或依赖混入 QWbot。

## 已完成的第一批整合

已在 QWbot 中吸收以下能力：

- SQLite 持久化 `event_receipts`，跨重连和进程重启去重 OneBot 消息。
- SQLite 持久化 `outbound_receipts`，同一入站事件的同一回复只允许发送一次。
- OneBot 账号 `self_id` 一致性检查、连接/事件/消息健康遥测和心跳日志。
- 稳定的 `账号:group:群号` / `账号:direct:QQ号` 会话编号。
- 私聊白名单和群白名单策略统一封装。
- Markdown 人格目录动态扫描，增加 `/人格列表` 命令。
- 保留现有 QWbot 的隐私授权、SQLite 记忆、RAG、Tavily 和 DeepSeek 链路。

## 推荐整合顺序

### 第 1 步：QWbot 内吸收安全设计

保持当前 `bot\\transport` 为唯一自动回复事件入口，仅移植：事件去重、账号/群范围校验、发送幂等键、心跳状态和 UNKNOWN 回执处理。

### 第 2 步：增强人格和学习

参考 Tulpa 的人格快照和候选记忆机制，在 QWbot 现有 `persona/`、`storage/`、`memory/` 中实现，不复用 Tulpa 数据库。

### 第 3 步：可选 MCP 侧车

如需让 Codex/Claude 等外部 Agent 查询 QQ 历史、群文件或手动发送，再单独运行 Tulpa MCP，并使用独立数据目录和授权。它不参与 QWbot 的自动模型回复。

## 当前验证

- Tulpa 源码已成功拉取。
- `chatlocal`、`app.py`、`app_mcp.py` 已通过 Python 编译检查。
- 未安装 Tulpa 依赖、未创建 `.env`、未启动 Tulpa、未修改 NapCat 配置。
- QWbot 当前保持停止状态。

