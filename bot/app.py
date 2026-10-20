"""Production entrypoint for the modular QWbot service."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from core.config import load_config
from core.dispatcher import MessageDispatcher
from core.single_instance import InstanceAlreadyRunning, InstanceLock
from core.startup_update import daily_update_due, mark_daily_update, run_startup_update
from core.proactive import ProactiveChatManager
from llm.deepseek_client import DeepSeekClient
from storage.store import Store
from transport.onebot11_client import OneBot11Client


LOG = logging.getLogger("qwbot.app")
BASE = Path(__file__).resolve().parent


async def run(config_path: Path) -> None:
    config = load_config(config_path)
    knowledge_config = config.get("knowledge", {})
    if knowledge_config.get("update_on_start", True):
        marker_path = Path(knowledge_config["update_marker_path"])
        once_per_day = bool(knowledge_config.get("update_once_per_day", True))
        if not once_per_day or daily_update_due(marker_path):
            LOG.info("running startup knowledge refresh before OneBot11 connection")
            # Mark the attempt before running so repeated launches cannot start
            # another expensive refresh on the same calendar day.
            if once_per_day:
                mark_daily_update(marker_path)
            refreshed = await asyncio.to_thread(
                run_startup_update,
                BASE.parent,
                BASE,
                config_path.resolve(),
                int(knowledge_config.get("startup_update_timeout_seconds", 180)),
            )
            LOG.info("startup knowledge refresh complete: %s", "ok" if refreshed else "kept previous data")
        else:
            LOG.info("startup knowledge refresh skipped; already attempted today (%s)", marker_path)
    store = Store(
        config["storage"]["db_path"],
        retention_days=config["storage"].get("retention_days", 14),
    )
    store.cleanup()
    provider = str(config.get("llm", {}).get("provider", "deepseek")).strip().lower()
    if provider != "deepseek":
        raise ValueError(f"unsupported llm.provider: {provider}; this build supports DeepSeek only")
    llm = DeepSeekClient(config["deepseek"])
    LOG.info("LLM provider: DeepSeek model=%s thinking=%s", llm.model, llm.thinking)
    transport = OneBot11Client(
        config["onebot"]["ws_url"],
        access_token=config["onebot"].get("access_token", ""),
        reconnect_seconds=config["onebot"].get("reconnect_seconds", 5),
    )
    dispatcher = MessageDispatcher(
        config,
        store,
        llm,
        str(BASE / "persona" / "system.md"),
    )
    proactive = ProactiveChatManager(config, store, llm, dispatcher)
    proactive_task = asyncio.create_task(proactive.run(transport))
    persona_restore_task = asyncio.create_task(dispatcher.persona_restore_loop(transport))
    LOG.info("dispatcher registered; starting OneBot11 event loop")
    try:
        await transport.run(dispatcher.handle_raw)
    finally:
        proactive_task.cancel()
        persona_restore_task.cancel()
        await asyncio.gather(proactive_task, persona_restore_task, return_exceptions=True)
        await transport.stop()
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="QWbot OneBot11 service (DeepSeek)")
    parser.add_argument("--config", default=str(BASE / "config.json"))
    args = parser.parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        LOG.error("config not found: %s; copy config.stage1.example.json to config.json", config_path)
        return 2
    instance_lock = InstanceLock(BASE / "data" / "qwbot.lock")
    try:
        instance_lock.acquire()
    except InstanceAlreadyRunning as exc:
        LOG.error("QWbot is already running: %s", exc)
        return 3
    try:
        asyncio.run(run(config_path))
    except KeyboardInterrupt:
        LOG.info("stopped")
    finally:
        instance_lock.release()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
