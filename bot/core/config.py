"""Configuration loading without importing secrets from the legacy project."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "onebot": {
        "ws_url": "ws://127.0.0.1:3001",
        "access_token": "",
        "reconnect_seconds": 5,
    },
    "llm": {
        "provider": "deepseek",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_file": "secrets/deepseek_api_key.txt",
        "timeout_seconds": 45,
        "temperature": 0.7,
        "max_tokens": 600,
        "reasoning": {
            "model": "deepseek-flash",
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens": 1200,
        },
    },
    "access": {
        "allowed_group_ids": [],
        "allowed_private_user_ids": [],
        "require_group_whitelist": True,
        "admin_user_ids": [],
        "group_consent_confirmed": False,
        "require_user_consent": True,
        "allow_private_messages": False,
    },
    "storage": {
        "db_path": "../data/qwbot.sqlite3",
        "retention_days": 14,
    },
    "knowledge": {
        "path": "../knowledge",
        "max_results": 4,
        "max_chars": 2600,
        "chunk_chars": 1800,
        "min_score": 6,
        "index_path": "../data/rag.sqlite3",
        "update_on_start": True,
        "update_once_per_day": True,
        "update_marker_path": "../data/knowledge_update_date.txt",
        "startup_update_timeout_seconds": 180,
    },
    "assets": {
        "path": "../assets",
        "max_file_bytes": 8388608,
        "max_segments": 8,
    },
    "media": {
        "auto_emotion_enabled": True,
        "auto_media_cooldown_seconds": 600,
        "auto_emotion_probability": 0.7,
    },
    "hearthstone": {
        "enabled": True,
        "decks_path": "../knowledge/hearthstone/decks/latest.json",
        "cards_path": "../data/hearthstone_cards.json",
        "max_decks": 3,
    },
    "search": {
        "enabled": True,
        "provider": "auto",
        "tavily_api_key_env": "TAVILY_API_KEY",
        "tavily_api_key_file": "secrets/tavily_api_key.txt",
        "brave_api_key_env": "BRAVE_SEARCH_API_KEY",
        "searxng_url": "",
        "max_results": 4,
        "max_query_chars": 240,
        "max_content_chars": 900,
        "timeout_seconds": 15,
        "cache_seconds": 900,
        "language": "zh-CN",
        "country": "CN",
        "auto": True,
    },
    "memory": {
        "candidate_extraction_enabled": True,
        "max_candidates_per_message": 2,
    },
    "proactive": {
        "enabled": False,
        "group_ids": [],
        "interval_seconds": 45,
        "min_silence_seconds": 20,
        "cooldown_seconds": 180,
        "active_window_seconds": 900,
        "max_replies_per_hour": 5,
        "max_reply_chars": 120,
        "water_group_mode": True,
    },
    "persona": {
        "directory": "persona",
        "active": "system",
    },
    "persona_switch": {
        "enabled": True,
        "sakura_persona": "sakura_winter",
        "black_persona": "sakura_black",
        "sakura_avatar": "../assets/stickers/sakura_official_thumb.png",
        "black_avatar": "../assets/avatars/black_sakura_qq_v2.png",
        "insult_threshold": 3,
        "quiet_seconds": 1800,
        "insult_keywords": [
            "婊子", "鸡", "烧鸡", "烧货", "骚货", "贱人", "臭婊",
            "傻逼", "傻比", "煞笔", "沙币", "杀币", "傻吊", "傻屌", "傻卵",
            "脑残", "脑瘫", "智障", "弱智", "废物", "蠢货", "垃圾",
            "狗东西", "狗逼", "畜生", "出生", "孤儿", "小丑", "沙雕", "下头", "神经病", "有病",
            "草泥马", "cnm", "nmsl", "wdnmd", "mdzz", "sb", "ntm", "fw",
        ],
        "directed_names": ["樱", "间桐樱", "黑樱", "桜", "sakura"],
    },
    "tulpa": {
        "style_guidance": True,
    },
    "transport": {
        "event_dedup_ttl_seconds": 604800,
        "outbound_retry_after_seconds": 30,
    },
    "bot": {
        "max_context_messages": 10,
        "max_user_history": 5,
        "max_user_dialogue_messages": 8,
        "max_group_reference_messages": 4,
        "max_context_chars": 3000,
        "max_prompt_chars": 9000,
        "max_memory_chars": 1800,
        "max_user_memory_chars": 1200,
        "max_reply_chars": 600,
        "max_reply_parts": 4,
        "reply_split_delay_seconds": 0.35,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    result = _merge(DEFAULTS, config)
    db_path = Path(result["storage"]["db_path"])
    if not db_path.is_absolute():
        result["storage"]["db_path"] = str((config_path.parent / db_path).resolve())
    knowledge_path = Path(result["knowledge"]["path"])
    if not knowledge_path.is_absolute():
        result["knowledge"]["path"] = str((config_path.parent / knowledge_path).resolve())
    index_path = Path(result["knowledge"].get("index_path", ""))
    if str(index_path) and not index_path.is_absolute():
        result["knowledge"]["index_path"] = str((config_path.parent / index_path).resolve())
    assets_path = Path(result.get("assets", {}).get("path", ""))
    if str(assets_path) and not assets_path.is_absolute():
        result["assets"]["path"] = str((config_path.parent / assets_path).resolve())
    for key in ("decks_path", "cards_path"):
        deck_path = Path(result.get("hearthstone", {}).get(key, ""))
        if str(deck_path) and not deck_path.is_absolute():
            result["hearthstone"][key] = str((config_path.parent / deck_path).resolve())
    marker_path = Path(result["knowledge"].get("update_marker_path", ""))
    if str(marker_path) and not marker_path.is_absolute():
        result["knowledge"]["update_marker_path"] = str((config_path.parent / marker_path).resolve())
    key_file = Path(result["search"].get("tavily_api_key_file", ""))
    if str(key_file) and not key_file.is_absolute():
        result["search"]["tavily_api_key_file"] = str((config_path.parent / key_file).resolve())
    deepseek_key_file = Path(result["deepseek"].get("api_key_file", ""))
    if str(deepseek_key_file) and not deepseek_key_file.is_absolute():
        result["deepseek"]["api_key_file"] = str((config_path.parent / deepseek_key_file).resolve())
    result["access"]["allowed_group_ids"] = {
        int(value) for value in result["access"].get("allowed_group_ids", [])
    }
    result["access"]["admin_user_ids"] = {
        int(value) for value in result["access"].get("admin_user_ids", [])
    }
    result["access"]["allowed_private_user_ids"] = {
        int(value) for value in result["access"].get("allowed_private_user_ids", [])
    }
    persona_dir = Path(result["persona"].get("directory", ""))
    if str(persona_dir) and not persona_dir.is_absolute():
        result["persona"]["directory"] = str((config_path.parent / persona_dir).resolve())
    for avatar_key in ("sakura_avatar", "black_avatar"):
        avatar_path = Path(result["persona_switch"].get(avatar_key, ""))
        if str(avatar_path) and not avatar_path.is_absolute():
            result["persona_switch"][avatar_key] = str((config_path.parent / avatar_path).resolve())
    return result
