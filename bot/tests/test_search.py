"""Unit tests for provider selection and explicit web-search routing."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from storage.store import Store
from web.search import SearchClient, SearchResponse, SearchResult


class FakeTransport:
    def __init__(self) -> None:
        self.group: list[tuple[int, str]] = []
        self.private: list[tuple[int, str]] = []

    async def send_group_message(self, group_id: int, message: str) -> None:
        self.group.append((group_id, message))

    async def send_private_message(self, user_id: int, message: str) -> None:
        self.private.append((user_id, message))


class FakeLLM:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "联网回答"


class FakeSearch:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.queries: list[str] = []

    async def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response

    @staticmethod
    def selected_provider() -> str:
        return "fake"


def _group_search_event() -> str:
    return json.dumps(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 123,
            "user_id": 42,
            "message_id": 7,
            "message": [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": "/搜索 DeepSeek-V4 最新版本"}},
            ],
            "sender": {"user_id": 42, "nickname": "测试"},
        },
        ensure_ascii=False,
    )


class SearchTests(unittest.TestCase):
    def test_provider_without_credentials_is_unconfigured(self) -> None:
        client = SearchClient({"provider": "tavily"})
        response = client._search_sync("test")
        self.assertEqual("unconfigured", response.status)

    def test_tavily_key_can_be_loaded_from_file(self) -> None:
        key_file = Path(__file__).with_name("_search_test_key.txt")
        try:
            key_file.write_text("# comment\n tvly-test-secret\n", encoding="utf-8")
            client = SearchClient(
                {"provider": "tavily", "tavily_api_key_file": str(key_file)}
            )
            self.assertEqual("tavily", client.selected_provider())
        finally:
            key_file.unlink(missing_ok=True)

    def test_explicit_search_results_are_added_to_llm_prompt(self) -> None:
        store = Store(":memory:")
        store.agree(123, 42)
        config = {
            "access": {
                "allowed_group_ids": [123],
                "admin_user_ids": [],
                "group_consent_confirmed": True,
                "allow_private_messages": False,
            },
            "storage": {"retention_days": 14},
            "bot": {"max_reply_chars": 600},
            "knowledge": {},
            "memory": {"candidate_extraction_enabled": False},
            "search": {"enabled": True, "auto": True},
        }
        response = SearchResponse(
            "ok",
            "fake",
            "DeepSeek-V4 最新版本",
            (SearchResult("官方公告", "版本说明摘要", "https://example.com/deepseek-v4"),),
        )
        search = FakeSearch(response)
        llm = FakeLLM()
        transport = FakeTransport()
        dispatcher = MessageDispatcher(config, store, llm, "missing-persona.md")
        dispatcher.search = search  # type: ignore[assignment]

        asyncio.run(dispatcher.handle_raw(transport, _group_search_event()))

        self.assertEqual(["DeepSeek-V4 最新版本"], search.queries)
        self.assertEqual([(123, "联网回答")], transport.group)
        self.assertIn("联网搜索结果", llm.messages[1]["content"])
        self.assertIn("https://example.com/deepseek-v4", llm.messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
