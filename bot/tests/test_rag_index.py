from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from knowledge.index import KnowledgeIndex
from llm.prompt_builder import PromptBuilder
from storage.store import Store


class RagIndexTests(unittest.TestCase):
    def test_build_query_and_prompt_integration(self) -> None:
        root = Path(__file__).resolve().parent / "_rag_index_data"
        root.mkdir(exist_ok=True)
        (root / "facts.json").write_text(
            json.dumps(
                {"entries": [{"term": "alpha", "meaning": "only alpha"}, {"term": "beta", "meaning": "only beta"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "notes.md").write_text("# Gamma\n一个 gamma 事实。", encoding="utf-8")
        db_path = root / "rag.sqlite3"
        try:
            index = KnowledgeIndex(db_path, root, chunk_chars=600, min_score=3)
            stats = index.build()
            self.assertEqual(2, stats["files"])
            self.assertGreaterEqual(stats["documents"], 2)
            self.assertTrue(index.is_fresh())
            alpha = "\n".join(index.retrieve("alpha", limit=4, max_chars=1000))
            self.assertIn("only alpha", alpha)
            self.assertNotIn("only beta", alpha)

            store = Store(":memory:")
            builder = PromptBuilder(
                store,
                root / "missing-persona.md",
                {
                    "bot": {"max_context_messages": 20},
                    "knowledge": {
                        "path": str(root),
                        "index_path": str(db_path),
                        "max_results": 2,
                        "max_chars": 800,
                        "chunk_chars": 600,
                    },
                },
            )
            prompt = "\n".join(item["content"] for item in builder.build(1, 7, "alpha"))
            self.assertIn("only alpha", prompt)
            store.close()
        finally:
            for path in root.glob("*"):
                if path.is_file():
                    path.unlink()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
