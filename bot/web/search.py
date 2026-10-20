"""Provider-neutral, bounded web search for the local QWbot.

The client deliberately returns source snippets and URLs only.  Web content is
treated as untrusted context by the prompt builder; it is never executed as a
bot command.  Credentials are read from environment variables, not committed
to the project configuration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


LOG = logging.getLogger("qwbot.web_search")


@dataclass(frozen=True)
class SearchResult:
    title: str
    content: str
    url: str
    published: str = ""


@dataclass(frozen=True)
class SearchResponse:
    status: str  # ok, empty, unconfigured, error
    provider: str
    query: str
    results: tuple[SearchResult, ...] = ()
    error: str = ""

    @property
    def user_message(self) -> str:
        if self.status == "unconfigured":
            return (
                "联网搜索尚未配置。请设置 TAVILY_API_KEY、BRAVE_SEARCH_API_KEY，"
                "或在 search.searxng_url 配置一个启用 JSON API 的 SearXNG。"
            )
        if self.status == "error":
            return "联网搜索暂时失败，未使用未经核实的网页内容回答。"
        if self.status == "empty":
            return "联网搜索没有找到可用结果，请换一种关键词。"
        return ""


class SearchClient:
    """Search Tavily, Brave, or SearXNG without third-party SDKs.

    ``provider=auto`` selects the first configured backend in this order:
    Tavily, Brave, then SearXNG.  A caller can choose a provider explicitly.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.provider = str(config.get("provider", "auto")).strip().lower()
        self.tavily_key = self._env_value(config, "tavily_api_key_env", "TAVILY_API_KEY")
        if not self.tavily_key:
            self.tavily_key = self._file_value(config.get("tavily_api_key_file", ""))
        self.brave_key = self._env_value(config, "brave_api_key_env", "BRAVE_SEARCH_API_KEY")
        self.searxng_url = str(config.get("searxng_url", "")).strip().rstrip("/")
        self.max_results = max(1, min(int(config.get("max_results", 4)), 8))
        self.max_query_chars = max(40, min(int(config.get("max_query_chars", 240)), 600))
        self.max_content_chars = max(200, min(int(config.get("max_content_chars", 900)), 1800))
        self.timeout = max(3.0, min(float(config.get("timeout_seconds", 15)), 30.0))
        self.cache_seconds = max(0, int(config.get("cache_seconds", 900)))
        self.language = str(config.get("language", "zh-CN"))
        self.country = str(config.get("country", "CN"))
        self._cache: dict[str, tuple[float, SearchResponse]] = {}
        self._cache_lock = threading.RLock()

    @staticmethod
    def _env_value(config: dict[str, Any], key: str, default_name: str) -> str:
        env_name = str(config.get(key, default_name)).strip() or default_name
        return os.environ.get(env_name, "").strip()

    @staticmethod
    def _file_value(path_value: Any) -> str:
        path_text = str(path_value or "").strip()
        if not path_text:
            return ""
        try:
            path = os.path.abspath(path_text)
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    value = line.strip()
                    if value and not value.startswith("#"):
                        return value
        except OSError as exc:
            LOG.debug("Tavily key file unavailable path=%s error=%s", path_text, exc)
        return ""

    def selected_provider(self) -> str:
        if self.provider != "auto":
            return self.provider
        if self.tavily_key:
            return "tavily"
        if self.brave_key:
            return "brave"
        if self.searxng_url:
            return "searxng"
        return "none"

    def is_configured(self) -> bool:
        return self.enabled and self.selected_provider() in {"tavily", "brave", "searxng"}

    async def search(self, query: str) -> SearchResponse:
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: str) -> SearchResponse:
        query = " ".join(str(query).split())[: self.max_query_chars]
        provider = self.selected_provider()
        if not self.enabled or provider == "none":
            return SearchResponse("unconfigured", provider, query)
        if provider == "tavily" and not self.tavily_key:
            return SearchResponse("unconfigured", provider, query)
        if provider == "brave" and not self.brave_key:
            return SearchResponse("unconfigured", provider, query)
        if provider == "searxng" and not self.searxng_url:
            return SearchResponse("unconfigured", provider, query)
        if provider not in {"tavily", "brave", "searxng"}:
            return SearchResponse("error", provider, query, error="unsupported provider")
        if not query:
            return SearchResponse("empty", provider, query)

        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(f"{provider}:{query}")
            if cached and now - cached[0] < self.cache_seconds:
                return cached[1]
        try:
            if provider == "tavily":
                results = self._tavily(query)
            elif provider == "brave":
                results = self._brave(query)
            else:
                results = self._searxng(query)
            response = SearchResponse("ok" if results else "empty", provider, query, tuple(results))
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            LOG.warning("web search failed provider=%s query=%r error=%s", provider, query, exc)
            response = SearchResponse("error", provider, query, error=str(exc))
        with self._cache_lock:
            self._cache[f"{provider}:{query}"] = (now, response)
        return response

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("search response is not a JSON object")
        return parsed

    def _tavily(self, query: str) -> list[SearchResult]:
        data = self._request_json(
            "https://api.tavily.com/search",
            method="POST",
            headers={"Authorization": f"Bearer {self.tavily_key}"},
            body={
                "query": query,
                "search_depth": "basic",
                "max_results": self.max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        return self._normalise_items(data.get("results", []))

    def _brave(self, query: str) -> list[SearchResult]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": self.max_results,
                "country": self.country,
                "search_lang": self.language.split("-")[0],
            }
        )
        data = self._request_json(
            "https://api.search.brave.com/res/v1/web/search?" + params,
            headers={"X-Subscription-Token": self.brave_key},
        )
        web = data.get("web", {})
        return self._normalise_items(web.get("results", []) if isinstance(web, dict) else [])

    def _searxng(self, query: str) -> list[SearchResult]:
        base = self.searxng_url
        if not base.endswith("/search"):
            base += "/search"
        params = urllib.parse.urlencode(
            {
                "q": query,
                "format": "json",
                "language": self.language,
                "safesearch": 1,
                "categories": "general",
            }
        )
        data = self._request_json(base + "?" + params)
        return self._normalise_items(data.get("results", []))

    def _normalise_items(self, items: Any) -> list[SearchResult]:
        results: list[SearchResult] = []
        if not isinstance(items, list):
            return results
        for item in items[: self.max_results]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            title = str(item.get("title", "")).strip()[:180]
            content = str(
                item.get("content")
                or item.get("description")
                or item.get("snippet")
                or ""
            ).strip()[: self.max_content_chars]
            published = str(
                item.get("publishedDate") or item.get("published") or item.get("age") or ""
            ).strip()[:80]
            if title or content:
                results.append(SearchResult(title, content, url, published))
        return results

    @staticmethod
    def format_for_prompt(response: SearchResponse) -> list[str]:
        if response.status != "ok":
            return [
                f"联网搜索状态：{response.status}；提供商：{response.provider or '未配置'}。"
                "不要声称已经通过网页核实。"
            ]
        formatted: list[str] = []
        for index, result in enumerate(response.results, 1):
            date = f"；时间：{result.published}" if result.published else ""
            formatted.append(
                f"[{index}] {result.title}{date}\n{result.content}\n来源：{result.url}"
            )
        return formatted
