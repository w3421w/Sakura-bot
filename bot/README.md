# bot/

生产入口是 `app.py`，只使用 DeepSeek：

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python app.py --config config.json
```

- `config.example.json`：完整生产配置示例
- `persona/`：人格 Markdown
- `knowledge/`：RAG 代码与本地副本
- `secrets/`：Key 占位说明（真实 Key 不会提交）
- `tests/`：单元测试

详见仓库根目录 `README.md`。
