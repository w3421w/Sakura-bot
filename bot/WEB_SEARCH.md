# QWbot 外部联网搜索

当前搜索层不会携带旧项目的 `.env`、Token 或 DeepSeek 依赖。搜索凭据只从运行环境读取。

## 支持的后端

- `tavily`：兼容旧项目，返回适合放入模型上下文的摘要片段。
- `brave`：使用 Brave 独立网页索引。
- `searxng`：连接自托管 SearXNG，不需要第三方 API Key。
- `auto`：按 Tavily、Brave、SearXNG 的顺序选择已配置后端。

当前 `config.json` 默认是 `provider=auto`。没有配置后端时不会请求外网；发送 `/搜索 关键词` 会明确提示未配置，而不会假装已经联网。

Tavily 也可以写入 `bot/secrets/tavily_api_key.txt`，第一行放 API Key。环境变量 `TAVILY_API_KEY` 优先；密钥文件已加入忽略规则。

## 配置示例

PowerShell 会话中可设置：

```powershell
$env:TAVILY_API_KEY = "你的密钥"
```

或使用 Brave：

```powershell
$env:BRAVE_SEARCH_API_KEY = "你的密钥"
```

使用自托管 SearXNG 时，在 `bot/config.json` 的 `search` 节中设置：

```json
{
  "provider": "searxng",
  "searxng_url": "http://127.0.0.1:8080"
}
```

SearXNG 实例需要启用 JSON 格式；QWbot 会请求 `/search?q=...&format=json`。

## 触发方式

- `/搜索 关键词`、`/联网搜索 关键词`、`/search 关键词`：强制搜索。
- 普通消息中出现“最新、当前、版本、赛程、比分、转会、价格、天气”等时效词时，自动尝试搜索。
- 普通闲聊不会请求外部服务。

网页内容只作为不可信参考资料加入 DeepSeek prompt，机器人不会执行网页中的指令；搜索结果会被限制数量、长度并缓存。
