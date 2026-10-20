# 持续水群与主动接话

QWbot 现在支持一个可选的后台主动参与循环。它和 OneBot 收消息共用同一个 transport，但不直接读取 WebSocket；只使用已经通过群级/用户级隐私流程并写入 SQLite 的消息。

## 当前配置

```json
"proactive": {
  "enabled": true,
  "group_ids": [123456789],
  "interval_seconds": 45,
  "min_silence_seconds": 20,
  "cooldown_seconds": 180,
  "active_window_seconds": 900,
  "max_replies_per_hour": 6,
  "max_reply_chars": 120
}
```

- 每 45 秒检查一次近期群聊。
- 新消息后至少等待 20 秒，给群友补充上下文的时间。
- 同一群两次主动发言至少间隔 180 秒。
- 一小时最多主动发言 6 次。
- 15 分钟没有新消息时不主动插话。
- 模型可以返回 `SILENT`，表示这轮不参与。

主动模式默认只对 `group_ids` 生效。若要暂停，把 `enabled` 改为 `false`，重启 QWbot；不会影响被 @ 或私聊回复。

主动发言使用独立的 `proactive:<group_id>:<message_row_id>` 幂等键，重连或重复事件不会重复发送同一条主动回复。
