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
    for item in os.getenv("CO_CHAT_PROVIDERS", "gpt,claude,grok,deepseek,codex").split(",")
    if item.strip()
]
CODEX_BIN = os.getenv("CO_CHAT_CODEX_BIN", "codex")
CHROME_CHANNEL = os.getenv("CO_CHAT_CHROME_CHANNEL", "chrome")
CHROME_EXECUTABLE_PATH = os.getenv(
    "CO_CHAT_CHROME_EXECUTABLE",
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
)

# WSL-focused defaults for login reliability with a real Chrome profile.
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--start-maximized",
]
NAVIGATION_TIMEOUT_MS = int(os.getenv("CO_CHAT_NAVIGATION_TIMEOUT_MS", "90000"))
ACTION_TIMEOUT_MS = int(os.getenv("CO_CHAT_ACTION_TIMEOUT_MS", "30000"))
