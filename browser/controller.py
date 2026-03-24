from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Error, Page

from core.logger import JsonlLogger
from core.message import utc_now_iso


class AIController:
    MIN_REPLY_LENGTH = 6
    STABLE_POLLS_REQUIRED = 2

    def __init__(
        self,
        name: str,
        url: str,
        selectors: dict[str, Any],
        logger: JsonlLogger,
    ) -> None:
        self.name = name
        self.url = url
        self.selectors = selectors
        self.logger = logger
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.ready = False
        self.last_error: str | None = None
        self.last_emitted_assistant: str | None = None
        self.last_assistant_timestamp: str | None = None
        self.selector_health = "unknown"
        self._pending_assistant: str | None = None
        self._pending_seen_count = 0
        self._page_lock = asyncio.Lock()

    async def start(
        self,
        context: BrowserContext,
        url: str | None = None,
        selectors: dict[str, Any] | None = None,
    ) -> None:
        async with self._page_lock:
            await self._start_locked(context=context, url=url, selectors=selectors)

    async def send(self, text: str) -> bool:
        async with self._page_lock:
            try:
                if self.page is None or self.page.is_closed():
                    if self.context is None:
                        raise RuntimeError("No browser context available.")
                    await self._start_locked(context=self.context)

                assert self.page is not None
                await self._wait_for_ready()

                input_selector = self.selectors.get("input")
                if not input_selector:
                    raise ValueError(f"Missing input selector for {self.name}")

                input_locator = self.page.locator(input_selector).first
                await input_locator.wait_for(state="visible")
                await input_locator.click()
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                await self.page.keyboard.insert_text(text)

                send_selector = self.selectors.get("send_button")
                if send_selector:
                    send_locator = self.page.locator(send_selector)
                    if await send_locator.count() > 0:
                        await send_locator.first.click()
                    else:
                        await self.page.keyboard.press("Enter")
                else:
                    await self.page.keyboard.press("Enter")

                self.ready = True
                self.last_error = None
                self._set_selector_health("ok")
                return True
            except Exception as exc:
                await self._handle_error("send", exc)
                return False

    async def read_latest(self) -> str | None:
        async with self._page_lock:
            try:
                if self.page is None or self.page.is_closed():
                    self.ready = False
                    return None

                latest = await self._latest_assistant_text()
                if not latest or not self._is_substantive(latest):
                    return None
                if await self._is_streaming():
                    return None
                if latest == self.last_emitted_assistant:
                    return None

                if latest != self._pending_assistant:
                    self._pending_assistant = latest
                    self._pending_seen_count = 1
                    return None

                self._pending_seen_count += 1
                if self._pending_seen_count < self.STABLE_POLLS_REQUIRED:
                    return None

                self.last_emitted_assistant = latest
                self.last_assistant_timestamp = utc_now_iso()
                self._pending_assistant = None
                self._pending_seen_count = 0
                self.last_error = None
                self.ready = True
                self._set_selector_health("ok")
                return latest
            except Exception as exc:
                await self._handle_error("read_latest", exc)
                return None

    def is_ready(self) -> bool:
        return self.ready and self.page is not None and not self.page.is_closed()

    def status(self) -> dict[str, str]:
        if self.page is None:
            state = "not-started"
        elif self.page.is_closed():
            state = "closed"
        elif self.last_error:
            state = f"error: {self.last_error}"
        elif self.ready:
            state = "ready"
        else:
            state = "starting"

        return {
            "name": self.name,
            "ready": "yes" if self.is_ready() else "no",
            "state": state,
            "page_url": self.page.url if self.page is not None and not self.page.is_closed() else self.url,
            "last_assistant_timestamp": self.last_assistant_timestamp or "-",
            "last_error": self.last_error or "-",
            "selector_health": self.selector_health,
        }

    async def _wait_for_ready(self) -> None:
        if self.page is None:
            raise RuntimeError(f"{self.name} has no page.")

        self._validate_selector_config()
        ready_selector = self.selectors.get("ready") or self.selectors.get("input")
        assert ready_selector is not None

        try:
            await self.page.wait_for_selector(ready_selector, state="visible")
        except Exception as exc:
            self._set_selector_health(f"ready-failed: {exc}")
            raise
        self.ready = True

    async def _latest_assistant_text(self) -> str | None:
        if self.page is None:
            return None

        messages_selector = self.selectors.get("assistant_messages")
        if not messages_selector:
            self._set_selector_health("missing: assistant_messages")
            raise ValueError(f"Missing assistant_messages selector for {self.name}")

        locator = self.page.locator(messages_selector)
        count = await locator.count()
        if count == 0:
            return None

        latest = await locator.nth(count - 1).inner_text()
        return self._normalize_text(latest)

    async def _is_streaming(self) -> bool:
        if self.page is None:
            return False

        streaming_selector = self.selectors.get("streaming_indicator")
        if not streaming_selector:
            return False

        locator = self.page.locator(streaming_selector)
        if await locator.count() == 0:
            return False
        return await locator.first.is_visible()

    async def _get_or_create_page(self, context: BrowserContext) -> Page:
        target_host = urlparse(self.url).netloc
        for page in context.pages:
            try:
                if target_host and target_host in page.url:
                    return page
            except Error:
                continue
        return await context.new_page()

    async def _handle_error(self, action: str, exc: Exception) -> None:
        self.ready = False
        self.last_error = f"{action}: {exc}"
        self._set_selector_health(f"error during {action}")
        await self.logger.log_event(
            source=self.name,
            target="hub",
            content=str(exc),
            kind="error",
            status=action,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.split()).strip()

    async def _start_locked(
        self,
        context: BrowserContext,
        url: str | None = None,
        selectors: dict[str, Any] | None = None,
    ) -> None:
        self.context = context
        if url is not None:
            self.url = url
        if selectors is not None:
            self.selectors = selectors

        self.page = await self._get_or_create_page(context)
        await self.page.bring_to_front()

        if not self.page.url or self.page.url == "about:blank":
            await self.page.goto(self.url, wait_until="domcontentloaded")
        else:
            target_host = urlparse(self.url).netloc
            if target_host and target_host not in self.page.url:
                await self.page.goto(self.url, wait_until="domcontentloaded")

        await self._wait_for_ready()
        existing = await self._latest_assistant_text()
        self.last_emitted_assistant = existing
        self.last_assistant_timestamp = utc_now_iso() if existing else None
        self._pending_assistant = None
        self._pending_seen_count = 0
        self.ready = True
        self.last_error = None
        self._set_selector_health("ok")

    def _validate_selector_config(self) -> None:
        missing: list[str] = []

        if not self.selectors.get("input"):
            missing.append("input")
        if not (self.selectors.get("ready") or self.selectors.get("input")):
            missing.append("ready")
        if not self.selectors.get("assistant_messages"):
            missing.append("assistant_messages")

        if missing:
            self._set_selector_health(f"missing: {', '.join(sorted(set(missing)))}")
            raise ValueError(f"Missing selectors for {self.name}: {', '.join(sorted(set(missing)))}")

        self._set_selector_health("ok")

    def _set_selector_health(self, health: str) -> None:
        self.selector_health = health

    def _is_substantive(self, text: str) -> bool:
        return len(text.strip()) >= self.MIN_REPLY_LENGTH
