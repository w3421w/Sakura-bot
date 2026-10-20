"""CLI for building the persistent QWbot knowledge index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.config import load_config
from knowledge.index import KnowledgeIndex


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the QWbot local RAG index")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    knowledge = config["knowledge"]
    index = KnowledgeIndex(
        knowledge["index_path"],
        knowledge["path"],
        chunk_chars=knowledge.get("chunk_chars", 1800),
        min_score=knowledge.get("min_score", 6),
    )
    print(json.dumps(index.build(), ensure_ascii=False, indent=2))
    print(json.dumps(index.stats(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
