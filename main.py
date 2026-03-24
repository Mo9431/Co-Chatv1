from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from playwright.async_api import async_playwright

from browser.registry import build_controllers
from config.config import (
    ACTION_TIMEOUT_MS,
    BOT_TOKEN,
    BROWSER_ARGS,
    CHAT_ID,
    ENABLE_TELEGRAM,
    ENABLED_PROVIDERS,
    HEADLESS,
    LOG_DIR,
    MAX_AUTO_ROUNDS,
    NAVIGATION_TIMEOUT_MS,
    POLL_INTERVAL,
    SESSION_DIR,
)
from config.selectors import SELECTORS, URLS
from core.logger import JsonlLogger
from core.state import RuntimeState
from interfaces.cli import CLI
from interfaces.telegram_control import TelegramControl
from router import Router


def ensure_runtime_dirs() -> None:
    Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


async def run() -> int:
    ensure_runtime_dirs()

    logger = JsonlLogger(LOG_DIR)
    state = RuntimeState(max_auto_rounds=MAX_AUTO_ROUNDS)
    telegram_control: TelegramControl | None = None
    controllers = {}

    async with async_playwright() as playwright:
        controllers = await build_controllers(
            browser_type=playwright.chromium,
            session_root=SESSION_DIR,
            headless=HEADLESS,
            providers=ENABLED_PROVIDERS,
            urls=URLS,
            selector_map=SELECTORS,
            logger=logger,
            state=state,
            browser_args=BROWSER_ARGS,
            action_timeout_ms=ACTION_TIMEOUT_MS,
            navigation_timeout_ms=NAVIGATION_TIMEOUT_MS,
        )

        router = Router(
            controllers=controllers,
            logger=logger,
            state=state,
            poll_interval=POLL_INTERVAL,
        )
        cli = CLI(router)

        loop = asyncio.get_running_loop()

        def handle_stop_signal() -> None:
            router.request_shutdown()

        for signame in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(getattr(signal, signame), handle_stop_signal)
            except (AttributeError, NotImplementedError):
                pass

        monitor_task = router.start_monitoring()

        try:
            if ENABLE_TELEGRAM:
                telegram_control = TelegramControl(
                    router=router,
                    bot_token=BOT_TOKEN,
                    chat_id=CHAT_ID,
                )
                await telegram_control.start()

            await logger.log_event(
                source="system",
                target="hub",
                content="Co-Chat started.",
                kind="system",
                status="ok",
            )
            await cli.run()
        finally:
            router.request_shutdown()
            await monitor_task

            if telegram_control is not None:
                await telegram_control.stop()

            await logger.log_event(
                source="system",
                target="hub",
                content="Co-Chat shutting down.",
                kind="system",
                status="ok",
            )
            await _close_controller_contexts(controllers)

    return 0


async def _close_controller_contexts(controllers: dict[str, object]) -> None:
    seen_context_ids: set[int] = set()
    for controller in controllers.values():
        context = getattr(controller, "context", None)
        if context is None or id(context) in seen_context_ids:
            continue
        seen_context_ids.add(id(context))
        await context.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
