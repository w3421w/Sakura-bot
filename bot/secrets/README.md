# 本地搜索密钥

将 Tavily API Key 写入同目录的 `tavily_api_key.txt`，第一行填写密钥即可。

文件会被 QWbot 自动读取；环境变量 `TAVILY_API_KEY` 优先于此文件。不要把真实密钥提交到 Git 或发送到聊天中。

## DeepSeek

将 DeepSeek API Key 写入同目录的 `deepseek_api_key.txt`，第一行填写密钥；
或设置环境变量 `DEEPSEEK_API_KEY`（环境变量优先）。QWbot 当前默认使用
DeepSeek `deepseek-flash` 的非思考模式，密钥不会写入 `config.json`。
