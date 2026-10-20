# DeepSeek + Tulpa 合并说明

本次合并把旧项目的成熟能力接入 E 盘的模块化 QWbot，不覆盖或启动旧入口，也不读取旧项目的 `.env`。

## 当前运行链路

`NapCat OneBot11 -> transport -> dispatcher/privacy/store/RAG -> DeepSeek API -> OneBot11`

旧本地模型客户端已移除；当前项目只保留 DeepSeek 后端，`bot/config.json` 的 `llm.provider` 固定为 `deepseek`。

## DeepSeek 配置

- 地址：`https://api.deepseek.com/chat/completions`
- 默认模型：`deepseek-flash`
- 默认 `thinking: disabled`，避免把思考内容混进 QQ 回复
- Key 优先读取环境变量 `DEEPSEEK_API_KEY`，其次读取 `bot/secrets/deepseek_api_key.txt`
- 真实 Key 不写入 JSON、代码或旧 D 盘项目

启动前任选一种方式配置 Key：

```powershell
$env:DEEPSEEK_API_KEY = "你的Key"
# 或把 Key 单独写入 bot\secrets\deepseek_api_key.txt
python bot\app.py
```

## 从 D 盘迁移的能力

- OneBot/NapCat 通信与私聊支持：继续使用 E 盘现有 `transport/`，避免旧入口的重复收包。
- SQLite 消息、同意/退出、用户画像、群记忆：继续使用 E 盘 `storage/`，保留事件和出站幂等。
- DeepSeek/Tavily/RAG：将旧项目的 DeepSeek 请求思路接入 `llm/deepseek_client.py`，搜索和知识召回仍由 E 盘模块负责。
- LOL/无畏契约知识：E 盘已有对应 JSON/Markdown 数据；与 D 盘同名数据保持兼容，不覆盖 E 盘已有扩展。
- 管理命令和隐私说明：会根据当前 LLM provider 明确提示消息会发送到 DeepSeek API。

## Tulpa 能力的吸收方式

未把 Tulpa 作为第二个 OneBot 消费者运行，避免重复回复。E 盘现有 `core/tulpa_compat.py` 继续负责会话范围、事件幂等和出站幂等；`PromptBuilder` 吸收 Tulpa 的回复原则：短句、贴合当前会话、不伪造第一人称事实、不泄露内部判断。历史消息仍受原有授权和上下文上限约束。

Tulpa 源码保留在 `third_party/Tulpa` 供审阅，固定提交记录见 `TULPA_INTEGRATION.md`。
