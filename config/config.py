from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


HEADLESS = _env_bool("CO_CHAT_HEADLESS", False)
ENABLE_TELEGRAM = _env_bool("CO_CHAT_ENABLE_TELEGRAM", False)
BOT_TOKEN = os.getenv("CO_CHAT_BOT_TOKEN", "")
CHAT_ID = int(os.getenv("CO_CHAT_CHAT_ID", "0"))
POLL_INTERVAL = float(os.getenv("CO_CHAT_POLL_INTERVAL", "1.0"))
MAX_AUTO_ROUNDS = int(os.getenv("CO_CHAT_MAX_AUTO_ROUNDS", "3"))
SESSION_DIR = os.getenv("CO_CHAT_SESSION_DIR", "sessions")
LOG_DIR = os.getenv("CO_CHAT_LOG_DIR", "logs")
ENABLED_PROVIDERS = [
    item.strip()
    for item in os.getenv("CO_CHAT_PROVIDERS", "gpt,claude,grok").split(",")
    if item.strip()
]

# Useful defaults for WSL2 and a visible browser session.
BROWSER_ARGS = [
    "--disable-dev-shm-usage",
    "--start-maximized",
    "--restore-last-session",
]
NAVIGATION_TIMEOUT_MS = int(os.getenv("CO_CHAT_NAVIGATION_TIMEOUT_MS", "90000"))
ACTION_TIMEOUT_MS = int(os.getenv("CO_CHAT_ACTION_TIMEOUT_MS", "30000"))
