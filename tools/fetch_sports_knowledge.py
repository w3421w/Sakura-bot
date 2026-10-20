"""Refresh public sports data for the QWbot RAG library.

The script is deliberately dependency-free. It downloads only public JSON
metadata/data and writes compact, provenance-preserving records under the
production knowledge directory. No API keys, cookies, tokens, or QQ data are
used.
"""

from __future__ import annotations

import argparse
import json
import shutil
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UA = "QWbot-RAG-refresh/1.0 (+local knowledge builder)"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get_json(url: str, timeout: int = 35) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout, context=CTX) as response:
        return json.loads(response.read().decode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def fetched() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refresh_lol(root: Path, report: list[str]) -> None:
    base = "https://ddragon.leagueoflegends.com"
    versions = get_json(f"{base}/api/versions.json")
    patch = str(versions[0])
    locale = "zh_CN"
    out = root / "lol" / "current"
    champions = get_json(f"{base}/cdn/{patch}/data/{locale}/champion.json").get("data", {})
    champion_records = []
    for champion in champions.values():
        champion_records.append({
            "主题": "英雄联盟英雄资料",
            "版本": patch,
            "英雄": champion.get("name"),
            "英文ID": champion.get("id"),
            "称号": champion.get("title"),
            "简介": champion.get("blurb"),
            "定位标签": champion.get("tags", []),
            "基础属性": champion.get("info", {}),
            "来源": f"Data Dragon {patch}",
        })
    write_json(out / "champions.json", {"source_url": f"{base}/cdn/{patch}/data/{locale}/champion.json", "fetched_at": fetched(), "records": champion_records})

    item_data = get_json(f"{base}/cdn/{patch}/data/{locale}/item.json").get("data", {})
    item_records = []
    for item_id, item in item_data.items():
        if not item.get("name") or not item.get("description"):
            continue
        item_records.append({
            "主题": "英雄联盟装备资料",
            "版本": patch,
            "装备": item.get("name"),
            "装备ID": item_id,
            "说明": item.get("description"),
            "简述": item.get("plaintext", ""),
            "价格": item.get("gold", {}),
            "标签": item.get("tags", []),
            "来源": f"Data Dragon {patch}",
        })
    write_json(out / "items.json", {"source_url": f"{base}/cdn/{patch}/data/{locale}/item.json", "fetched_at": fetched(), "records": item_records})

    runes = get_json(f"{base}/cdn/{patch}/data/{locale}/runesReforged.json")
    rune_records = []
    for tree in runes:
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                rune_records.append({
                    "主题": "英雄联盟符文资料",
                    "版本": patch,
                    "符文系": tree.get("name"),
                    "符文": rune.get("name"),
                    "简介": rune.get("longDesc"),
                    "短说明": rune.get("shortDesc"),
                    "来源": f"Data Dragon {patch}",
                })
    write_json(out / "runes.json", {"source_url": f"{base}/cdn/{patch}/data/{locale}/runesReforged.json", "fetched_at": fetched(), "records": rune_records})
    write_md(out / "README.md", f"""# LOL 公共资料\n\n- 来源：Riot Games Data Dragon 官方静态数据\n- 补丁：{patch}\n- 抓取时间（UTC）：{fetched()}\n- 本目录只保留英雄、装备、符文的结构化检索字段；平衡性和数值可能随补丁变化，回答时应注明版本。\n- 来源入口：https://developer.riotgames.com/docs/lol\n""")
    report.append(f"LOL Data Dragon {patch}: {len(champion_records)} heroes, {len(item_records)} items, {len(rune_records)} runes")


def refresh_valorant(root: Path, report: list[str]) -> None:
    base = "https://valorant-api.com/v1"
    out = root / "valorant" / "current"
    endpoints = {
        "agents": "agents?language=zh-CN",
        "maps": "maps?language=zh-CN",
        "weapons": "weapons?language=zh-CN",
        "competitive_tiers": "competitivetiers?language=zh-CN",
    }
    counts = []
    for name, endpoint in endpoints.items():
        payload = get_json(f"{base}/{endpoint}")
        records = []
        for item in payload.get("data", []):
            if name == "agents":
                abilities = [{"名称": a.get("displayName"), "说明": a.get("description")} for a in (item.get("abilities") or []) if isinstance(a, dict)]
                records.append({"主题": "无畏契约特工资料", "特工": item.get("displayName"), "简介": item.get("description"), "定位": (item.get("role") or {}).get("displayName"), "技能": abilities, "可用": item.get("isPlayableCharacter"), "来源": "Valorant API"})
            elif name == "maps":
                records.append({"主题": "无畏契约地图资料", "地图": item.get("displayName"), "区域": item.get("coordinates"), "简介": item.get("tacticalDescription"), "来源": "Valorant API"})
            elif name == "weapons":
                shop = item.get("shopData") or {}
                records.append({"主题": "无畏契约武器资料", "武器": item.get("displayName"), "类别": (item.get("category") or "").split("::")[-1], "价格": shop.get("cost"), "弹匣": (item.get("weaponStats") or {}).get("magazineSize"), "来源": "Valorant API"})
            else:
                records.append({"主题": "无畏契约竞技段位资料", "段位": item.get(" tierName") or item.get("tierName"), "段位ID": item.get("tier"), "来源": "Valorant API"})
        write_json(out / f"{name}.json", {"source_url": f"{base}/{endpoint}", "fetched_at": fetched(), "records": records})
        counts.append(f"{name}={len(records)}")
    write_md(out / "README.md", f"""# VALORANT 公共资料\n\n- 来源：valorant-api.com 公共 API（由社区维护的结构化游戏资料镜像）\n- 抓取时间（UTC）：{fetched()}\n- 数据可能随游戏版本更新；不把段位、平衡或赛事状态当作永久事实。\n- 来源项目：https://github.com/weedeej/valorant-api-json\n""")
    report.append("VALORANT API: " + ", ".join(counts))


def refresh_vtuber(root: Path, report: list[str]) -> None:
    url = "https://vdb.vtbs.moe/json/list.json"
    payload = get_json(url, timeout=60)
    records = []
    vtbs = payload.get("vtbs", []) if isinstance(payload, dict) else payload
    for item in vtbs if isinstance(vtbs, list) else []:
        accounts = []
        for account in item.get("accounts", []) or []:
            if not isinstance(account, dict):
                continue
            accounts.append({"平台": account.get("platform"), "平台ID": account.get("id"), "名称": account.get("name")})
        records.append({"主题": "VTuber公开资料", "UUID": item.get("uuid"), "名称": item.get("name"), "类型": item.get("type"), "团体": item.get("group"), "账号": accounts, "来源": "VTuber数据库 vdb"})
    out = root / "vtuber"
    write_json(out / "vdb_list.json", {"source_url": url, "fetched_at": fetched(), "records": records})
    write_md(out / "README.md", f"""# VTuber 公共资料\n\n- 来源：VTuber Database (vdb.vtbs.moe) 公共 JSON 列表\n- 抓取时间（UTC）：{fetched()}\n- 仅用于公开频道、平台账号和团体名称检索；不推断、不收集或暴露现实身份/中之人隐私。\n- 来源项目：https://github.com/dd-center/vdb\n""")
    report.append(f"VTuber vdb: {len(records)} public channel records")


def refresh_nba(root: Path, report: list[str], third_party: Path) -> None:
    source = third_party / "nba-schedule-2025-26" / "nba_2025_26_schedule.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    out = root / "nba"
    write_json(out / source.name, {"source_url": "https://github.com/moizk/nba-schedule-2025-26", "fetched_at": fetched(), "records": payload})
    players_url = "https://raw.githubusercontent.com/bttmly/nba/master/data/players.json"
    players_payload = get_json(players_url)
    player_records = []
    for player in players_payload if isinstance(players_payload, list) else []:
        if isinstance(player, dict):
            player_records.append({"主题": "NBA公开球员名单", "姓名": f"{player.get('firstName', '')} {player.get('lastName', '')}".strip(), "球员ID": player.get("playerId"), "球队ID": player.get("teamId"), "来源": "bttmly/nba public players.json"})
    write_json(out / "players.json", {"source_url": players_url, "fetched_at": fetched(), "records": player_records})
    write_md(out / "README.md", f"""# NBA 公共赛程\n\n- 来源：Moiz K. Malik 的 NBA 2025-26 赛程整理\n- 授权：MIT（保留原项目 LICENSE）\n- 数据最后更新时间（赛程源文件）：{payload.get('last_updated', '')}\n- 附加公开球员名单：bttmly/nba（仅姓名与公开 ID，不含实时状态）\n- 抓取/整理时间（UTC）：{fetched()}\n- 赛程不是实时比分；回答当天比赛或结果时应先调用联网搜索确认。\n- 来源项目：https://github.com/moizk/nba-schedule-2025-26\n""")
    shutil.copy2(source.parent / "LICENSE", out / "LICENSE")
    report.append(f"NBA schedule: {len(payload.get('games', []))} games, players={len(player_records)}")


def refresh_football(root: Path, report: list[str]) -> None:
    out = root / "football"
    leagues = {"英超": "en.1", "西甲": "es.1", "德甲": "de.1", "意甲": "it.1", "法甲": "fr.1"}
    seasons = ["2026-27", "2025-26"]
    total = 0
    used = []
    for chinese, code in leagues.items():
        payload = None
        season = ""
        url = ""
        for candidate in seasons:
            candidate_url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{candidate}/{code}.json"
            try:
                payload = get_json(candidate_url, timeout=45)
                season, url = candidate, candidate_url
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                continue
        if payload is None:
            continue
        matches = []
        for match in payload.get("matches", []) if isinstance(payload, dict) else []:
            if isinstance(match, dict):
                matches.append({"联赛": chinese, "赛季": season, "轮次": match.get("round"), "日期": match.get("date"), "开球时间": match.get("time"), "主队": match.get("team1"), "客队": match.get("team2"), "比分": match.get("score"), "来源": "openfootball football.json"})
        write_json(out / f"{code}_{season}.json", {"source_url": url, "fetched_at": fetched(), "records": matches})
        total += len(matches)
        used.append(f"{chinese}({season})={len(matches)}")
    write_md(out / "README.md", f"""# 足球公共赛程与结果\n\n- 来源：openfootball/football.json\n- 授权：Public Domain（按源项目 README）\n- 抓取时间（UTC）：{fetched()}\n- 覆盖：英超、西甲、德甲、意甲、法甲；优先当前赛季，缺失时回退上一赛季。\n- 赛程/历史结果不是实时资讯；实时比赛、转会和热梗应先联网核验。\n- 来源项目：https://github.com/openfootball/football.json\n""")
    report.append("Football: " + (", ".join(used) if used else "no league file fetched"))


def refresh_hearthstone(root: Path, report: list[str]) -> None:
    url = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90, context=CTX) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records = []
    for card in payload if isinstance(payload, list) else []:
        if not isinstance(card, dict):
            continue
        records.append({
            "主题": "炉石传说可收藏卡牌",
            "卡牌": card.get("name"),
            "卡牌ID": card.get("id"),
            "类型": card.get("type"),
            "职业": card.get("cardClass"),
            "费用": card.get("cost"),
            "攻击": card.get("attack"),
            "生命": card.get("health"),
            "稀有度": card.get("rarity"),
            "系列": card.get("set"),
            "法术派系": card.get("spellSchool"),
            "卡牌文本": card.get("text"),
            "关键词": card.get("mechanics", []),
            "来源": "HearthstoneJSON / HearthSim",
        })
    out = root / "hearthstone"
    write_json(out / "cards_collectible_zhCN.json", {"source_url": url, "fetched_at": fetched(), "records": records})
    write_md(out / "README.md", f"""# 炉石传说公共卡牌资料\n\n- 来源：[HearthstoneJSON](https://hearthstonejson.com/) / HearthSim\n- 接口：{url}\n- 抓取时间（UTC）：{fetched()}\n- 当前文件包含可收藏卡牌的中文名称、职业、费用、身材、系列、卡牌文本和关键词。\n- 卡牌文本与环境强度会随版本变化；实时卡组、胜率、补丁和赛事信息仍需联网核验。\n- 卡牌名称、文本和美术等知识产权归 Blizzard Entertainment 等权利人所有，本目录仅用于个人本地检索。\n""")
    report.append(f"Hearthstone cards: {len(records)} collectible cards")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"knowledge")
    parser.add_argument("--third-party", default=r"third_party")
    args = parser.parse_args()
    root = Path(args.root)
    report: list[str] = []
    for func in (refresh_lol, refresh_valorant, refresh_vtuber, refresh_hearthstone):
        try:
            func(root, report)
        except Exception as exc:
            report.append(f"{func.__name__} FAILED: {exc}")
    try:
        refresh_nba(root, report, Path(args.third_party))
    except Exception as exc:
        report.append(f"refresh_nba FAILED: {exc}")
    try:
        refresh_football(root, report)
    except Exception as exc:
        report.append(f"refresh_football FAILED: {exc}")
    print("\n".join(report))
    return 0 if not any("FAILED" in line for line in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
