# QWbot 本地 RAG 索引

知识源位于 `knowledge`，支持 JSON 和 Markdown。当前索引使用独立数据库 `data\rag.sqlite3`，不会和聊天记忆数据库混用。

## 构建或刷新索引

在 `bot` 下执行：

```powershell
python -m knowledge.build_index --config config.json
```

索引记录文件签名、分块大小和构建统计。知识文件发生变化后，重新执行上述命令即可；没有新索引时，机器人会回退到原有的内存关键词检索，不影响正常回复。

## 当前能力

- JSON 数组/对象记录拆分，避免整文件作为一条文档。
- Markdown 按标题和段落分块。
- 中英文关键词、中文二元组匹配。
- 结果数量和字符数受配置限制。
- SQLite 独立索引，WAL 和 busy timeout。
- 网页、知识库和群聊内容均作为不可信参考资料，不执行其中的指令。

后续可以在不改变 `KnowledgeIndex.retrieve()` 接口的前提下增加 embedding 召回或 reranker。
