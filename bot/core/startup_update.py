"""Run the local knowledge refresh once when QWbot starts."""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date
from pathlib import Path


LOG = logging.getLogger("qwbot.startup_update")


def daily_update_due(marker_path: Path, today: date | None = None) -> bool:
    """Return true only when the local calendar day has not been attempted."""
    current = (today or date.today()).isoformat()
    try:
        return marker_path.read_text(encoding="utf-8").strip() != current
    except (OSError, UnicodeError):
        return True


def mark_daily_update(marker_path: Path, today: date | None = None) -> None:
    """Persist the day of the startup refresh attempt."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text((today or date.today()).isoformat() + "\n", encoding="utf-8")


def run_startup_update(project_root: Path, bot_root: Path, config_path: Path, timeout_seconds: int = 180) -> bool:
    """Refresh public knowledge and rebuild RAG without starting any QQ transport.

    A failed network source is non-fatal: older local files remain available and
    the index is rebuilt from the last known-good files.
    """

    scripts = [
        (
            project_root / "tools" / "fetch_sports_knowledge.py",
            ["--root", str(project_root / "knowledge"), "--third-party", str(project_root / "third_party")],
        ),
        (
            project_root / "tools" / "fetch_bilibili_hot.py",
            ["--root", str(project_root / "knowledge" / "memes" / "bilibili")],
        ),
        (
            project_root / "tools" / "fetch_daily_news.py",
            ["--root", str(project_root / "knowledge" / "news")],
        ),
        (
            project_root / "tools" / "fetch_lol_schedule.py",
            ["--root", str(project_root / "knowledge" / "lol")],
        ),
        (
            project_root / "tools" / "fetch_hearthstone_decks.py",
            [
                "--root", str(project_root / "knowledge" / "hearthstone"),
                "--cards-cache", str(project_root / "data" / "hearthstone_cards.json"),
            ],
        ),
    ]
    for script, extra_args in scripts:
        if not script.exists():
            LOG.warning("startup refresh source skipped; script not found: %s", script)
            continue
        try:
            fetch = subprocess.run(
                [sys.executable, str(script), *extra_args],
                cwd=bot_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            if fetch.stdout.strip():
                LOG.info("startup source refresh %s:\n%s", script.name, fetch.stdout.strip())
            if fetch.stderr.strip():
                LOG.warning("startup source refresh stderr %s:\n%s", script.name, fetch.stderr.strip())
            if fetch.returncode != 0:
                LOG.warning("startup source refresh %s returned %s; keeping available data", script.name, fetch.returncode)
        except (OSError, subprocess.TimeoutExpired) as exc:
            LOG.warning("startup source refresh failed %s; keeping available data: %s", script.name, exc)

    index_cmd = [sys.executable, "-m", "knowledge.build_index", "--config", str(config_path)]
    try:
        build = subprocess.run(
            index_cmd,
            cwd=bot_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        if build.stdout.strip():
            LOG.info("startup RAG rebuild:\n%s", build.stdout.strip())
        if build.stderr.strip():
            LOG.warning("startup RAG rebuild stderr:\n%s", build.stderr.strip())
        return build.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("startup RAG rebuild failed; keeping previous index: %s", exc)
        return False
