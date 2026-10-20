"""Fetch current League of Legends esports schedules for the local RAG.

The public schedule mirror exposes the same structured schedule data used by
LoL Esports and avoids scraping rendered cards.  Records are normalized to
China Standard Time so questions such as "24 日凌晨一点 IG 对 GEN" match the
knowledge index naturally.  Old seasons are discarded; recent and upcoming
matches are retained with provenance and a freshness timestamp.
"""

from __future__ import annotations

import argparse
import json
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_URL = "https://lolesports.net"
USER_AGENT = "QWbot-LoL-schedule-refresh/1.0"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
CHINA = ZoneInfo("Asia/Shanghai")


def fetch_json(url: str, timeout: int = 45):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=CTX) as response:
        return json.loads(response.read().decode("utf-8"))


def iso_china(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(CHINA).isoformat(timespec="minutes")


def normalize_match(match: dict, fetched_at: str) -> dict:
    team1 = match.get("team1") or {}
    team2 = match.get("team2") or {}
    start_utc = str(match.get("startTime") or "")
    code1 = str(team1.get("code") or "TBD")
    code2 = str(team2.get("code") or "TBD")
    name1 = str(team1.get("name") or code1)
    name2 = str(team2.get("name") or code2)
    china_time = iso_china(start_utc) if start_utc else ""
    china_dt = datetime.fromisoformat(china_time) if china_time else None
    if china_dt is not None:
        hour_text = f"{china_dt.hour}点"
        chinese_hour = {0: "零点", 1: "一点", 2: "两点", 3: "三点", 4: "四点", 5: "五点"}.get(china_dt.hour, hour_text)
        if china_dt.hour < 6:
            natural_time = f"{china_dt.month}月{china_dt.day}日凌晨{chinese_hour}"
        elif china_dt.hour < 12:
            natural_time = f"{china_dt.month}月{china_dt.day}日上午{china_dt.hour}点"
        else:
            natural_time = f"{china_dt.month}月{china_dt.day}日{china_dt.hour}点"
    else:
        hour_text = ""
        natural_time = ""
    return {
        "主题": "LOL电竞赛程",
        "赛事": match.get("leagueName") or match.get("leagueSlug") or "LoL Esports",
        "赛段": match.get("blockName") or "",
        "比赛ID": str(match.get("id") or ""),
        "状态": match.get("state") or "",
        "开赛时间UTC": start_utc,
        "开赛时间中国": china_time,
        "日期中国": china_time[:10] if china_time else "",
        "自然语言时间": natural_time,
        "检索关键词": f"{natural_time} {china_dt.day if china_dt else ''}日凌晨{hour_text} {code1} VS {code2} IG GEN 赛程",
        "主队": name1,
        "主队简称": code1,
        "客队": name2,
        "客队简称": code2,
        "对阵": f"{code1} vs {code2}（{name1} 对 {name2}）",
        "赛制": match.get("strategy") or "",
        "结果": {
            "主队胜场": team1.get("wins", 0),
            "客队胜场": team2.get("wins", 0),
            "主队结果": team1.get("outcome"),
            "客队结果": team2.get("outcome"),
        },
        "来源": "LoL Esports 公开赛程数据镜像",
        "来源链接": f"{BASE_URL}/",
        "抓取时间": fetched_at,
        "时效说明": "赛程与对阵是时间敏感信息；回答当天比赛、临时换人或赛果时应联网核验。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"knowledge\lol")
    parser.add_argument("--past-days", type=int, default=7)
    parser.add_argument("--future-days", type=int, default=60)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    lower = now - timedelta(days=max(0, args.past_days))
    upper = now + timedelta(days=max(1, args.future_days))
    fetched_at = now.isoformat(timespec="seconds")

    leagues = fetch_json(f"{BASE_URL}/api/leagues")
    wanted = {"worlds", "lpl", "lck", "lec", "lcs", "msi", "first_stand", "lcp"}
    records: list[dict] = []
    seen: set[str] = set()
    source_leagues: list[str] = []
    for league in leagues if isinstance(leagues, list) else []:
        if str(league.get("slug")) not in wanted:
            continue
        league_id = str(league.get("id") or "")
        slug = str(league.get("slug") or "")
        if not league_id:
            continue
        payload = fetch_json(f"{BASE_URL}/api/schedule?leagueId={league_id}")
        source_leagues.append(slug)
        for match in (payload.get("matches") or []) if isinstance(payload, dict) else []:
            if not isinstance(match, dict):
                continue
            raw_time = str(match.get("startTime") or "")
            try:
                start = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start < lower or start > upper:
                continue
            match_id = str(match.get("id") or "")
            if not match_id or match_id in seen:
                continue
            seen.add(match_id)
            records.append(normalize_match(match, fetched_at))

    records.sort(key=lambda item: (item.get("开赛时间UTC", ""), item.get("比赛ID", "")))
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_url": f"{BASE_URL}/api/schedule",
        "source_note": "公开赛程数据镜像，页面标注数据来自 lolesports.com",
        "fetched_at": fetched_at,
        "window": {"past_days": args.past_days, "future_days": args.future_days},
        "leagues": source_leagues,
        "records": records,
    }
    (root / "esports_schedule.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# LOL 电竞赛程（自动更新）",
        "",
        f"抓取时间（UTC）：{fetched_at}",
        f"覆盖赛事：{', '.join(source_leagues)}",
        "时间均为中国标准时间（UTC+8）",
        "",
    ]
    for item in records:
        lines.append(
            f"- {item['开赛时间中国']}｜{item['赛事']} {item['赛段']}｜"
            f"{item['对阵']}｜{item['赛制']}｜状态：{item['状态']}"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 来源为公开赛程结构化数据，页面标注数据来自 LoL Esports。",
            "- 仅保留最近 7 天与未来 60 天，避免旧赛季污染检索。",
            "- 比赛时间、对阵、临时换人和赛果属于时间敏感信息，回答时应优先联网核验。",
        ]
    )
    (root / "esports_schedule.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"LOL esports schedule: {len(records)} matches; leagues={','.join(source_leagues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
