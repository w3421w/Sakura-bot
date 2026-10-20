"""Fetch and normalize public RSS news for the QWbot daily RAG refresh.

This is a source-oriented collector, not a search query.  It reads publisher
feeds directly, keeps provenance and publication time, removes duplicates, and
writes a bounded JSON corpus plus a human-readable daily digest.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin


USER_AGENT = "QWbot-daily-news-refresh/1.0 (+local RAG builder)"
SOURCES: tuple[dict[str, str], ...] = (
    {
        "id": "bbc_football",
        "topic": "足球",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "publisher": "BBC Sport",
    },
    {
        "id": "guardian_football",
        "topic": "足球",
        "url": "https://www.theguardian.com/football/rss",
        "publisher": "The Guardian",
    },
    {
        "id": "espn_nba",
        "topic": "NBA",
        "url": "https://www.espn.com/espn/rss/nba/news",
        "publisher": "ESPN",
    },
    {
        "id": "espn_general",
        "topic": "体育",
        "url": "https://www.espn.com/espn/rss/news",
        "publisher": "ESPN",
    },
)

HTML_SOURCES: tuple[dict[str, str], ...] = (
    {
        "id": "lol_esports_official",
        "topic": "LOL电竞",
        "url": "https://lolesports.com/en-US/news",
        "publisher": "LoL Esports 官方",
    },
    {
        "id": "valorant_esports_official",
        "topic": "VALORANT电竞",
        "url": "https://valorantesports.com/en-US/news",
        "publisher": "VALORANT Esports 官方",
    },
)

LPL_API_BASE = "https://apps.game.qq.com/wmp/v3.1/"


def _clean(value: Any, limit: int = 1000) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _text(element: ET.Element | None, *names: str) -> str:
    if element is None:
        return ""
    for name in names:
        child = element.find(name)
        if child is not None and child.text:
            return _clean(child.text)
    return ""


def fetch_xml(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_html(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_lpl_news(collected_at: str, limit: int, timeout: int) -> list[dict[str, Any]]:
    """Read the public JSONP feed used by the official LPL news page."""
    query = urlencode(
        {
            "p0": 3,
            "p1": "searchNewsKeywordsList",
            "page": 1,
            "pagesize": max(1, min(limit, 50)),
            "order": "sIdxTime",
            "r0": "script",
            "r1": "NewsObj",
            "type": "iTag",
            "id": "1260,1261,1262,1263,1264,1496,1570,2105",
            "source": "web_pc",
        }
    )
    url = LPL_API_BASE + "?" + query
    raw = fetch_html(url, timeout)
    match = re.search(r"NewsObj\s*=\s*(\{.*\})\s*;?\s*$", raw, re.DOTALL)
    if not match:
        raise ValueError("LPL official feed returned unexpected JSONP")
    payload = json.loads(match.group(1))
    rows = ((payload.get("msg") or {}).get("result") or []) if isinstance(payload, dict) else []
    records: list[dict[str, Any]] = []
    for row in rows[: max(1, limit)]:
        if not isinstance(row, dict):
            continue
        title = _clean(row.get("sTitle"), 240)
        news_id = str(row.get("iNewsId") or "").strip()
        if not title or not news_id:
            continue
        link = str(row.get("sUrl") or row.get("sRedirectURL") or "").strip()
        if link.startswith("//"):
            link = "https:" + link
        if not link:
            link = f"https://lol.qq.com/news/detail.shtml?docid={news_id}"
        summary = _clean(row.get("sExt1") or row.get("sExt2") or "", 600)
        records.append(
            {
                "主题": "LPL",
                "标题": title,
                "摘要": summary,
                "来源": "LPL官方/腾讯游戏",
                "来源ID": "lpl_official_api",
                "发布时间": _clean(row.get("iTime") or ""),
                "链接": link,
                "抓取时间": collected_at,
                "记录ID": hashlib.sha256(("lpl:" + news_id).encode("utf-8")).hexdigest()[:16],
                "时效说明": "LPL 官方公开资讯；比赛结果、赛程和选手动态以原文及实时赛果为准。",
            }
        )
    return records


def parse_feed(source: dict[str, str], payload: bytes, collected_at: str, limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    rows = root.findall(".//item")
    if not rows:
        rows = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    records: list[dict[str, Any]] = []
    for row in rows[: max(1, limit)]:
        title = _text(row, "title", "{http://www.w3.org/2005/Atom}title")
        link = _text(row, "link", "{http://www.w3.org/2005/Atom}link")
        if not link:
            link_node = row.find("{http://www.w3.org/2005/Atom}link")
            link = str(link_node.attrib.get("href", "")) if link_node is not None else ""
        summary = _text(
            row,
            "description",
            "summary",
            "content",
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
        )
        published = _text(row, "pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published")
        if not title or not link:
            continue
        key = hashlib.sha256((link or title).encode("utf-8")).hexdigest()[:16]
        records.append(
            {
                "主题": source["topic"],
                "标题": title,
                "摘要": summary,
                "来源": source["publisher"],
                "来源ID": source["id"],
                "发布时间": published,
                "链接": link,
                "抓取时间": collected_at,
                "记录ID": key,
                "时效说明": "这是公开 RSS 的时间敏感新闻，只用于话题和事实线索；回答最新事实时仍需核验原文。",
            }
        )
    return records


def parse_html_news(source: dict[str, str], payload: str, collected_at: str, limit: int) -> list[dict[str, Any]]:
    """Extract article cards from the official Riot esports news pages.

    The pages are server-rendered and expose article links/titles in the HTML;
    this intentionally avoids executing JavaScript or crawling article bodies.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    link_pattern = re.compile(r'href="([^\"]*/news/[^\"]*)"', re.IGNORECASE)
    for match in link_pattern.finditer(payload):
        raw_link = html.unescape(match.group(1))
        link = urljoin(source["url"], raw_link)
        if link in seen:
            continue
        seen.add(link)
        block = payload[match.end() : payload.find("</a>", match.end())]
        title_match = re.search(r'textStyle_headline/sm">(.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        summary_match = re.search(r'textStyle_body/lg">(.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        title = _clean(title_match.group(1) if title_match else "", 240)
        summary = _clean(summary_match.group(1) if summary_match else "", 600)
        if not title:
            continue
        key = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
        records.append(
            {
                "主题": source["topic"],
                "标题": title,
                "摘要": summary,
                "来源": source["publisher"],
                "来源ID": source["id"],
                "发布时间": "",
                "链接": link,
                "抓取时间": collected_at,
                "记录ID": key,
                "时效说明": "这是官方赛事新闻页的时间敏感资料；回答最新赛况时仍需核验原文和比赛数据。",
            }
        )
        if len(records) >= max(1, limit):
            break
    return records


def write_outputs(root: Path, records: list[dict[str, Any]], collected_at: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "daily_news.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["主题"]), []).append(record)
    lines = ["# 每日公开新闻汇总", "", f"抓取时间（UTC）：{collected_at}", ""]
    for topic, items in grouped.items():
        lines.extend([f"## {topic}", ""])
        for item in items:
            summary = f"：{item['摘要']}" if item["摘要"] else ""
            lines.append(f"- [{item['标题']}]({item['链接']})（{item['来源']}，{item['发布时间']}）{summary}")
        lines.append("")
    lines.extend(
        [
            "## 使用规则",
            "",
            "- 本文件由公开 RSS 源直接抓取、去重和字段归一化生成，不是搜索结果拼接。",
            "- 标题、摘要和发布时间保留来源链接；不把新闻摘要当作永久事实。",
        ]
    )
    (root / "daily_digest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public RSS feeds and build a normalized daily news corpus")
    parser.add_argument("--root", type=Path, default=Path(r"knowledge\news"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args(argv)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: list[str] = []
    for source in SOURCES:
        try:
            parsed = parse_feed(source, fetch_xml(source["url"], args.timeout), collected_at, args.limit)
        except (OSError, urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            failures.append(f"{source['id']}: {exc}")
            continue
        for record in parsed:
            if record["记录ID"] not in seen:
                seen.add(record["记录ID"])
                records.append(record)
    for source in HTML_SOURCES:
        try:
            parsed = parse_html_news(source, fetch_html(source["url"], args.timeout), collected_at, args.limit)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            failures.append(f"{source['id']}: {exc}")
            continue
        for record in parsed:
            if record["记录ID"] not in seen:
                seen.add(record["记录ID"])
                records.append(record)
    try:
        for record in fetch_lpl_news(collected_at, args.limit, args.timeout):
            if record["记录ID"] not in seen:
                seen.add(record["记录ID"])
                records.append(record)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"lpl_official_api: {exc}")
    write_outputs(args.root.resolve(), records, collected_at)
    report = {
        "root": str(args.root.resolve()),
        "records": len(records),
        "sources": len(SOURCES) + len(HTML_SOURCES) + 1,
        "failed_sources": failures,
        "collected_at": collected_at,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if records or not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
