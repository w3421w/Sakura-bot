"""Collect current Hearthstone deck articles from 旅法师营地 into local JSON.

Only structured facts are stored: article title, source link, class/archetype,
deck code, local card summary, and a short original strength note.  Article body
text is never written to the knowledge base.

The mobile site renders its article list server-side.  We read that list, follow
only deck-related articles, extract deck codes and nearby labels, then decode
each code into a local card summary.  Network failures are non-fatal: the old
``latest.json`` remains untouched.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

BOT_ROOT = Path(__file__).resolve().parents[1] / "bot"
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from knowledge.deck_code import (  # noqa: E402
    CLASS_NAMES,
    DeckCodeError,
    compact_card,
    decode_deckstring,
    load_card_map,
    summarize_deck,
)

CATEGORY_URL = "https://mob.iyingdi.com/fine/17"
ARTICLE_URL = "https://mob.iyingdi.com/post/{post_id}"
CARDS_URL = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
USER_AGENT = "QWbot-Hearthstone-deck-refresh/1.0"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
CODE_RE = re.compile(r"AAE[A-Za-z0-9+/]{20,}={0,2}")
POST_RE = re.compile(
    r'feed:\{id:(\d+),title:"((?:\\.|[^"\\])*)".{0,20000}?link:"([^"]+)"',
    re.S,
)
POSITIVE_RE = re.compile(r"卡组|日报|数据报|梯度|高分段|环境|上分|冲分|传说|标准|狂野", re.I)
NEGATIVE_RE = re.compile(r"热修|补丁|前瞻|乱斗|竞技场|开包|皮肤|商城|活动|公告|报名", re.I)
GENERIC_LABELS = {
    "卡组", "卡组推荐", "卡组代码", "代码", "标准", "狂野", "省流",
    "目录", "前言", "总结", "环境", "梯度", "数据",
}
STOP_NAME_PREFIXES = (
    "这套牌", "这套", "一套", "当前", "现在", "今天", "推荐", "还有",
    "其中", "比如", "例如", "这是", "这套是", "这套卡组", "鉴于", "由于",
    "因为", "所以", "但是", "而且", "不过", "其实", "另外", "作为", "相比",
)
ARCHETYPE_PREFIXES = (
    "法术", "龙", "任务", "控制", "快攻", "中速", "宇宙", "海盗", "鱼人",
    "野兽", "亡语", "铺场", "节奏", "光环", "灌注", "星舰", "发现", "污手",
    "大哥", "奇迹", "超生", "机械", "打2", "蛋", "随从", "鼠王", "绊索",
    "光铸", "拉法姆", "兆示", "艾雅", "激怒", "防战", "嘲讽", "元素",
    "恶魔", "蓝龙", "超凡", "青玉", "挖宝", "报告", "圣契", "奥秘", "武器",
    "复生", "吸血", "突袭", "冲锋", "战吼", "英雄", "泰坦", "酒馆", "脏",
    "偷", "洗", "烧", "宇宙", "彩虹", "偶数", "奇数",
)
STOP_NAMES = {
    "法师", "战士", "猎人", "术士", "牧师", "德鲁伊", "盗贼", "潜行者",
    "圣骑士", "萨满", "恶魔猎手", "死亡骑士", "卡组", "标准", "狂野",
    "职业", "环境", "天梯", "传说",
}
NAME_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{1,10}(?:萨|战|贼|猎|法|牧|术|德|骑|瞎|dk|DK)"
)
CLASS_KEYWORDS = (
    ("死亡骑士", "DEATHKNIGHT", ("死亡骑士", "死骑")),
    ("恶魔猎手", "DEMONHUNTER", ("恶魔猎手",)),
    ("德鲁伊", "DRUID", ("德鲁伊",)),
    ("猎人", "HUNTER", ("猎人",)),
    ("法师", "MAGE", ("法师",)),
    ("圣骑士", "PALADIN", ("圣骑士", "骑士")),
    ("牧师", "PRIEST", ("牧师",)),
    ("潜行者", "ROGUE", ("潜行者", "盗贼")),
    ("萨满", "SHAMAN", ("萨满",)),
    ("术士", "WARLOCK", ("术士",)),
    ("战士", "WARRIOR", ("战士",)),
)
CLASS_SUFFIXES = (
    ("萨", "SHAMAN", "萨满"),
    ("战", "WARRIOR", "战士"),
    ("贼", "ROGUE", "潜行者"),
    ("猎", "HUNTER", "猎人"),
    ("法", "MAGE", "法师"),
    ("牧", "PRIEST", "牧师"),
    ("术", "WARLOCK", "术士"),
    ("德", "DRUID", "德鲁伊"),
    ("骑", "PALADIN", "圣骑士"),
    ("瞎", "DEMONHUNTER", "恶魔猎手"),
    ("dk", "DEATHKNIGHT", "死亡骑士"),
)


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=CTX) as response:
        return response.read().decode("utf-8", "replace")


def fix_js_text(value: str) -> str:
    """Decode JS string escapes and the site's occasional GBK-in-UTF8 labels."""
    try:
        value = json.loads('"' + value + '"')
    except (ValueError, TypeError):
        pass
    try:
        repaired = value.encode("utf-8").decode("gbk")
        if any("\u4e00" <= char <= "\u9fff" for char in repaired):
            return repaired
    except (UnicodeError, LookupError):
        pass
    return value


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(value)).strip()


def parse_post_list(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in POST_RE.finditer(html):
        title = fix_js_text(match.group(2)).strip()
        link = match.group(3).replace("\\/", "/").replace("\\u002F", "/")
        post_id = ""
        found = re.search(r"/post/(\d+)", link)
        if found:
            post_id = found.group(1)
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        rows.append({"post_id": post_id, "title": title, "link": link})
    return rows


def is_deck_article(title: str) -> bool:
    if not POSITIVE_RE.search(title):
        return False
    if NEGATIVE_RE.search(title) and "卡组" not in title:
        return False
    return True


def article_date(title: str) -> str:
    match = re.search(r"(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})", title)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


class RichContentParser(HTMLParser):
    """Collect text blocks and deck-code asides from the article body."""

    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "blockquote", "li", "aside"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_content = False
        self.depth = 0
        self.current_tag = ""
        self.buffer: list[str] = []
        self.blocks: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = str(attrs_dict.get("class") or "")
        if tag == "div" and "rich-content" in classes:
            self.in_content = True
            self.depth = 1
            return
        if not self.in_content:
            return
        if tag == "div":
            self.depth += 1
            return
        if tag == "br":
            if self.current_tag:
                self.buffer.append("\n")
            return
        if tag in self.BLOCK_TAGS:
            self._flush()
            self.current_tag = tag
            self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        if not self.in_content:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth <= 0:
                self._flush()
                self.in_content = False
            return
        if tag in self.BLOCK_TAGS and self.current_tag == tag:
            self._flush()
            self.current_tag = ""

    def handle_data(self, data: str) -> None:
        if self.in_content and self.current_tag:
            self.buffer.append(data)

    def _flush(self) -> None:
        text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.buffer)).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        tag = self.current_tag
        self.buffer = []
        if not text:
            return
        if tag == "aside":
            match = CODE_RE.search(text)
            if match:
                self.blocks.append(("code", match.group(0)))
                return
        self.blocks.append((tag, text))


def extract_article(html: str) -> tuple[str, list[tuple[str, str]]]:
    title_match = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html, re.S)
    if not title_match:
        title_match = re.search(r"<title>(.*?)</title>", html, re.S)
    title = strip_tags(title_match.group(1)).replace(" -旅法师营地", "").strip() if title_match else ""
    parser = RichContentParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return title, parser.blocks


def article_class(text: str) -> tuple[str, str]:
    for zh, code, keywords in CLASS_KEYWORDS:
        if any(keyword.casefold() in text.casefold() for keyword in keywords):
            return zh, code
    # Deck names commonly use the one-character class suffix: 法术萨、龙战、任务法.
    for suffix, code, zh in CLASS_SUFFIXES:
        if re.search(rf"{re.escape(suffix)}(?![\u4e00-\u9fff])", text, re.I):
            return zh, code
    return "", ""


def deck_name_from_text(text: str) -> str:
    for match in NAME_RE.finditer(text):
        name = clean_label(match.group(0))
        for prefix in STOP_NAME_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
        if len(name) < 2 or name in STOP_NAMES:
            continue
        if name in GENERIC_LABELS:
            continue
        # Pick the last known archetype token inside a noisy sentence:
        # “鉴于龙战” -> “龙战”, “这套法术萨” -> “法术萨”.
        for start in range(len(name)):
            tail = name[start:]
            if any(tail.startswith(prefix) for prefix in ARCHETYPE_PREFIXES):
                name = tail
                break
        return name[:40]
    return ""


def clean_label(text: str) -> str:
    text = re.sub(r"^[\[【(（]\s*(标准|狂野|标准模式|狂野模式)\s*[\]】)）]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。;；")
    return text[:80]


def nearby_label(blocks: list[tuple[str, str]], index: int) -> str:
    for offset in range(1, 10):
        pos = index - offset
        if pos < 0:
            break
        tag, text = blocks[pos]
        if tag == "code" or not text:
            continue
        if tag in {"h2", "h3"}:
            label = clean_label(text)
            if label and label not in GENERIC_LABELS:
                return label[:40]
        label = deck_name_from_text(text)
        if label:
            return label
    for offset in range(1, 7):
        pos = index - offset
        if pos < 0:
            break
        tag, text = blocks[pos]
        if tag == "code" or not text:
            continue
        label = clean_label(text)
        if 2 <= len(label) <= 30 and label not in GENERIC_LABELS:
            return label
    return ""


def article_winrates(blocks: list[tuple[str, str]]) -> dict[str, float]:
    rates: dict[str, float] = {}
    for tag, text in blocks:
        if tag == "code" or "%" not in text:
            continue
        for match in NAME_RE.finditer(text):
            name = clean_label(match.group(0))
            for prefix in STOP_NAME_PREFIXES:
                if name.startswith(prefix):
                    name = name[len(prefix):]
            if len(name) < 2 or name in STOP_NAMES:
                continue
            tail = text[match.end() : match.end() + 18]
            percent = re.search(r"[（(]?\s*(\d{1,2}(?:\.\d+)?)\s*%", tail)
            if percent:
                value = float(percent.group(1))
                if 20 <= value <= 90:
                    rates.setdefault(name, value)
    return rates


def nearby_winrate(blocks: list[tuple[str, str]], index: int) -> float | None:
    window = blocks[max(0, index - 12) : min(len(blocks), index + 3)]
    for tag, text in window:
        if tag == "code":
            continue
        for match in re.finditer(r"(\d{1,2}(?:\.\d+)?)\s*%", text):
            value = float(match.group(1))
            if 20 <= value <= 90:
                return value
    return None


def nearby_tier(blocks: list[tuple[str, str]], index: int) -> str:
    window = " ".join(text for _, text in blocks[max(0, index - 7) : min(len(blocks), index + 3)])
    match = re.search(r"\bT([1-4])\b|梯度\s*([1-4])", window, re.I)
    if match:
        return "T" + (match.group(1) or match.group(2))
    return ""


def ensure_cards_cache(cache_path: Path, timeout: int = 30) -> dict[int, dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        try:
            if (datetime.now().timestamp() - cache_path.stat().st_mtime) < 7 * 86400:
                return load_card_map(cache_path)
        except OSError:
            pass
    try:
        payload = json.loads(fetch_text(CARDS_URL, timeout=timeout))
        cards: dict[str, Any] = {}
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                dbf_id = int(item["dbfId"])
            except (KeyError, TypeError, ValueError):
                continue
            cards[str(dbf_id)] = compact_card(item)
        if cards:
            cache_path.write_text(
                json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cards": cards}, ensure_ascii=False),
                encoding="utf-8",
            )
            return load_card_map(cache_path)
    except Exception as exc:  # network/cache errors are non-fatal
        print(f"card cache refresh failed: {exc}")
    return load_card_map(cache_path)


def infer_archetype(label: str, class_zh: str) -> str:
    text = clean_label(label)
    if not text:
        return f"{class_zh}卡组" if class_zh else "未标注"
    if "卡组" in text and len(text) > 12:
        text = re.sub(r"^(标准|狂野|高分段|传说|数据报|日报)[：: ]*", "", text)
    return text[:40]


def collect_article(
    post: dict[str, str],
    card_map: dict[int, dict[str, Any]],
    timeout: int,
) -> list[dict[str, Any]]:
    html = fetch_text(ARTICLE_URL.format(post_id=post["post_id"]), timeout=timeout)
    page_title, blocks = extract_article(html)
    title = page_title or post["title"]
    published = article_date(title) or article_date(post["title"])
    rates = article_winrates(blocks)
    records: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, (tag, value) in enumerate(blocks):
        if tag != "code":
            continue
        code = value.strip()
        if code in seen_codes:
            continue
        seen_codes.add(code)
        try:
            decoded = decode_deckstring(code)
        except DeckCodeError:
            continue
        label = nearby_label(blocks, index)
        label_class_zh, label_class_code = article_class(label + " " + title)
        summary = summarize_deck(decoded, card_map)
        decoded_class_zh = str(summary.get("class_zh") or "")
        decoded_class_code = str(summary.get("class") or "")
        if decoded_class_zh and decoded_class_zh != "未知":
            class_zh = decoded_class_zh
            class_code = decoded_class_code
        else:
            class_zh = label_class_zh
            class_code = label_class_code
        archetype = infer_archetype(label, class_zh)
        if label_class_zh and class_zh and label_class_zh != class_zh:
            # The nearby paragraph may belong to another deck section; trust the
            # decoded hero class and keep the label only as a generic name.
            archetype = f"{class_zh}卡组"
        winrate = rates.get(label) or rates.get(archetype) or nearby_winrate(blocks, index)
        tier = nearby_tier(blocks, index)
        key_cards = [
            {"name": item["name"], "count": item["count"], "cost": item.get("cost")}
            for item in summary.get("key_cards", []) if item.get("name")
        ]
        curve = summary.get("curve") or {}
        low_curve = int(curve.get("0-1", 0)) + int(curve.get("2", 0))
        if low_curve >= 18:
            curve_profile = "偏快攻/节奏"
        elif low_curve >= 12:
            curve_profile = "偏中速"
        else:
            curve_profile = "偏控制/后期"
        strength_note = (
            f"来源文章标注约 {winrate:g}% 胜率；曲线{curve_profile}（0-2费{low_curve}张）。"
            "胜率未独立复核，环境或分段变化后需重新验证。"
            if winrate is not None
            else f"来源未给出明确胜率；曲线{curve_profile}（0-2费{low_curve}张），"
            "强度需结合当前环境、分段和对局样本判断。"
        )
        record = {
            "id": f"iyingdi-{post['post_id']}-{len(records) + 1}",
            "topic": "炉石传说卡组",
            "source": "旅法师营地",
            "source_url": ARTICLE_URL.format(post_id=post["post_id"]),
            "title": title[:120],
            "published": published,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "class": class_code,
            "class_zh": class_zh or summary.get("class_zh") or "未知",
            "archetype": archetype,
            "name": f"{archetype}",
            "deck_code": code,
            "format": summary.get("format") or "",
            "total": summary.get("total") or 0,
            "curve": summary.get("curve") or {},
            "key_cards": key_cards,
            "winrate": winrate,
            "tier": tier,
            "curve_profile": curve_profile,
            "strength_note": strength_note,
            "summary": (
                f"{title[:80]} 收录的 {archetype}；"
                f"{('来源标注约 ' + format(winrate, 'g') + '% 胜率；') if winrate is not None else ''}"
                "结构化卡组资料，原文正文未入库。"
            ),
            "tags": [tag for tag in ("炉石传说", class_zh, archetype, summary.get("format")) if tag],
        }
        records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Hearthstone deck knowledge from iyingdi")
    parser.add_argument("--root", default=r"E:\01QQBOT\knowledge\hearthstone")
    parser.add_argument("--cards-cache", default=r"E:\01QQBOT\data\hearthstone_cards.json")
    parser.add_argument("--category-url", default=CATEGORY_URL)
    parser.add_argument("--max-articles", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    cards_cache = Path(args.cards_cache)
    cards = ensure_cards_cache(cards_cache, timeout=max(30, args.timeout))
    html = fetch_text(args.category_url, timeout=args.timeout)
    posts = [post for post in parse_post_list(html) if is_deck_article(post["title"])]
    posts = posts[: max(1, min(20, args.max_articles))]
    if not posts:
        print("no deck-related articles found; keeping previous data")
        return 1

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for post in posts:
        try:
            item_records = collect_article(post, cards, timeout=args.timeout)
        except Exception as exc:
            errors.append(f"{post['post_id']}: {exc}")
            continue
        records.extend(item_records)
    # Newest article first, de-duplicate deck codes while keeping the first hit.
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        code = str(record.get("deck_code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(record)
    if not unique:
        print("no valid deck codes found; keeping previous data")
        return 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "旅法师营地",
        "source_url": args.category_url,
        "article_count": len(posts),
        "deck_count": len(unique),
        "errors": errors[:10],
        "decks": unique,
    }
    output = root / "decks" / "latest.json"
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:12000])
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output)
    print(
        json.dumps(
            {
                "articles": len(posts),
                "decks": len(unique),
                "errors": errors[:3],
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
