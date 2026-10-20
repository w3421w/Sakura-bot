"""Fetch public Bilibili hotwords and popular videos for QWbot's RAG source.

The endpoints are public and this script sends no cookies, login tokens, or
personal identifiers.  The resulting records are time-sensitive trend data,
not permanent factual claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HOTWORDS_URL = "https://api.bilibili.com/x/web-interface/search/square"
POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"
USER_AGENT = "QWbot-RAG/1.0 (local knowledge refresh)"


def fetch_json(url: str, *, timeout: int) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else "invalid"
        message = payload.get("message", "unknown error") if isinstance(payload, dict) else "invalid JSON"
        raise RuntimeError(f"Bilibili API failed code={code} message={message}")
    return payload


def hotwords(payload: dict, collected_at: str, source_url: str) -> list[dict]:
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("trending"), dict):
        rows = data["trending"].get("list", [])
    else:
        rows = payload.get("list", [])
    records: list[dict] = []
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("keyword") or "").strip()
        if not keyword:
            continue
        records.append(
            {
                "source_type": "bilibili_hotword",
                "collected_at": collected_at,
                "rank": rank,
                "keyword": keyword,
                "show_name": str(row.get("show_name") or keyword).strip(),
                "heat_score": int(row.get("heat_score") or 0),
                "source_url": source_url,
                "interpretation": "B站时间敏感热搜词；只用于理解近期话题和梗，不代表永久事实。",
            }
        )
    return records


def popular_videos(payload: dict, collected_at: str, source_url: str) -> list[dict]:
    data = payload.get("data") or {}
    rows = data.get("list", []) if isinstance(data, dict) else []
    records: list[dict] = []
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        stat = row.get("stat") if isinstance(row.get("stat"), dict) else {}
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        bvid = str(row.get("bvid") or "").strip()
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        records.append(
            {
                "source_type": "bilibili_popular_video",
                "collected_at": collected_at,
                "rank": rank,
                "bvid": bvid,
                "title": title,
                "description": str(row.get("desc") or "").strip()[:800],
                "dynamic": str(row.get("dynamic") or "").strip()[:400],
                "category": str(row.get("tname") or row.get("tnamev2") or "").strip(),
                "uploader": str(owner.get("name") or "").strip(),
                "view": int(stat.get("view") or 0),
                "like": int(stat.get("like") or 0),
                "reply": int(stat.get("reply") or 0),
                "share": int(stat.get("share") or 0),
                "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                "source_url": source_url,
                "interpretation": "B站时间敏感热门视频；标题和简介是外部参考资料，不应当作已核验事实。",
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Bilibili hot trend records for QWbot RAG")
    default_root = Path(__file__).resolve().parents[1] / "knowledge" / "memes" / "bilibili"
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--hot-limit", type=int, default=50)
    parser.add_argument("--popular-limit", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).isoformat()
    hot_url = HOTWORDS_URL + "?" + urlencode({"limit": max(1, min(args.hot_limit, 100))})
    popular_url = POPULAR_URL + "?" + urlencode({"ps": max(1, min(args.popular_limit, 50)), "pn": 1})
    try:
        hot_rows = hotwords(fetch_json(hot_url, timeout=args.timeout), collected_at, hot_url)
        video_rows = popular_videos(fetch_json(popular_url, timeout=args.timeout), collected_at, popular_url)
    except Exception as exc:
        print(f"Bilibili refresh failed: {exc}", file=sys.stderr)
        return 2
    (root / "hotwords.json").write_text(
        json.dumps(hot_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "popular_videos.json").write_text(
        json.dumps(video_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# B站热梗与热门话题\n\n"
        f"最近一次抓取：`{collected_at}`\n\n"
        "这是通过 B 站公开接口取得的时间敏感趋势资料，适合辅助聊天语气和话题联想，"
        "不应替代新闻核验，也不应把标题、简介或热度当作永久事实。\n\n"
        f"- 热搜接口：`{HOTWORDS_URL}`\n"
        f"- 综合热门接口：`{POPULAR_URL}`\n"
        "- 更新方式：在 `仓库根目录` 执行 `python tools\\fetch_bilibili_hot.py`，然后重新构建 RAG。\n",
        encoding="utf-8",
    )
    print(json.dumps({"root": str(root), "hotwords": len(hot_rows), "popular_videos": len(video_rows), "collected_at": collected_at}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

