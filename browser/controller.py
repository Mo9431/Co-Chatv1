from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Error, Locator, Page

from core.logger import JsonlLogger
from core.message import utc_now_iso


class AIController:
    MIN_REPLY_LENGTH = 6
    STABLE_POLLS_REQUIRED = 2
    FALLBACK_STABLE_POLLS_REQUIRED = 3

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
        self.last_seen_hash: str | None = None
        self.last_seen_text: str | None = None
        self.last_emitted_hash: str | None = None
        self.last_sent_text: str | None = None
        self.last_assistant_timestamp: str | None = None
        self.selector_health = "unknown"
        self.stability_count = 0
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

                input_locator = await self._first_visible_locator(input_selector)
                if input_locator is None:
                    raise RuntimeError(
                        f"No visible input matched selector for {self.name}: {input_selector}"
                    )
                await input_locator.click()
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                await self.page.keyboard.insert_text(text)

                send_selector = self.selectors.get("send_btn")
                if send_selector:
                    send_locator = await self._first_visible_locator(send_selector)
                    try:
                        if send_locator is None:
                            raise RuntimeError("No visible send button matched selector.")
                        await send_locator.click(timeout=2000)
                    except Exception:
                        await self.page.keyboard.press("Enter")
                else:
                    await self.page.keyboard.press("Enter")

                self.last_sent_text = self._normalize_text(text)
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
                if self.last_sent_text and latest == self.last_sent_text:
                    return None

                latest_hash = self._hash_text(latest)
                if latest_hash == self.last_seen_hash:
                    self.stability_count += 1
                else:
                    self.last_seen_hash = latest_hash
                    self.last_seen_text = latest
                    self.stability_count = 1

                streaming_selector_configured, streaming_visible = await self._streaming_state()
                if streaming_visible:
                    return None

                required_polls = (
                    self.STABLE_POLLS_REQUIRED
                    if streaming_selector_configured
                    else self.FALLBACK_STABLE_POLLS_REQUIRED
                )
                if self.stability_count < required_polls:
                    return None
                if latest_hash == self.last_emitted_hash:
                    return None

                self.last_emitted_hash = latest_hash
                self.last_assistant_timestamp = utc_now_iso()
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
        ready_selector = self.selectors.get("input")
        assert ready_selector is not None

        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            locator = await self._first_visible_locator(ready_selector)
            if locator is not None:
                self.ready = True
                return
            await asyncio.sleep(0.25)

        detail = f"No visible input matched selector within timeout: {ready_selector}"
        self._set_selector_health(f"ready-failed: {detail}")
        raise RuntimeError(detail)
        self.ready = True

    async def _latest_assistant_text(self) -> str | None:
        if self.page is None:
            return None

        messages_selector = self.selectors.get("last_assistant")
        if not messages_selector:
            self._set_selector_health("missing: last_assistant")
            raise ValueError(f"Missing last_assistant selector for {self.name}")

        locator = self.page.locator(messages_selector)
        return await self._last_visible_text(locator)

    async def probe_selectors(self) -> dict[str, dict[str, str]]:
        async with self._page_lock:
            if (self.page is None or self.page.is_closed()) and self.context is not None:
                try:
                    await self._start_locked(context=self.context)
                except Exception as exc:
                    return {
                        "input": {"status": "FAIL", "detail": f"page unavailable: {exc}"},
                        "send_btn": {"status": "FAIL", "detail": f"page unavailable: {exc}"},
                        "last_assistant": {"status": "FAIL", "detail": f"page unavailable: {exc}"},
                        "streaming_indicator": {"status": "FAIL", "detail": f"page unavailable: {exc}"},
                    }

            return {
                "input": await self._probe_required_visible("input"),
                "send_btn": await self._probe_required_visible("send_btn"),
                "last_assistant": await self._probe_last_assistant(),
                "streaming_indicator": await self._probe_streaming_indicator(),
            }

    async def _streaming_state(self) -> tuple[bool, bool]:
        if self.page is None:
            return False, False

        streaming_selector = self.selectors.get("streaming_indicator")
        if not streaming_selector:
            return False, False

        try:
            locator = self.page.locator(streaming_selector)
            if await locator.count() == 0:
                return True, False
            return True, await locator.first.is_visible()
        except Exception:
            return False, False

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
        existing_hash = self._hash_text(existing) if existing else None
        self.last_seen_hash = existing_hash
        self.last_seen_text = existing
        self.last_emitted_hash = existing_hash
        self.last_assistant_timestamp = utc_now_iso() if existing else None
        self.stability_count = 0
        self.ready = True
        self.last_error = None
        self._set_selector_health("ok")

    def _validate_selector_config(self) -> None:
        missing: list[str] = []

        if not self.selectors.get("input"):
            missing.append("input")
        if not self.selectors.get("send_btn"):
            missing.append("send_btn")
        if "streaming_indicator" not in self.selectors:
            missing.append("streaming_indicator")
        if not self.selectors.get("last_assistant"):
            missing.append("last_assistant")

        if missing:
            self._set_selector_health(f"missing: {', '.join(sorted(set(missing)))}")
            raise ValueError(f"Missing selectors for {self.name}: {', '.join(sorted(set(missing)))}")

        self._set_selector_health("ok")

    def _set_selector_health(self, health: str) -> None:
        self.selector_health = health

    def _is_substantive(self, text: str) -> bool:
        return len(text.strip()) >= self.MIN_REPLY_LENGTH

    async def _probe_required_visible(self, key: str) -> dict[str, str]:
        if self.page is None:
            return {"status": "FAIL", "detail": "page unavailable"}

        selector = self.selectors.get(key)
        if not selector:
            return {"status": "FAIL", "detail": "selector missing"}

        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            if count == 0:
                return {"status": "FAIL", "detail": "no match"}
            visible_locator = await self._first_visible_locator(selector)
            if visible_locator is None:
                return {"status": "FAIL", "detail": f"matched {count}, none visible"}
            return {"status": "OK", "detail": "visible"}
        except Exception as exc:
            return {"status": "FAIL", "detail": str(exc)}

    async def _probe_last_assistant(self) -> dict[str, str]:
        if self.page is None:
            return {"status": "FAIL", "detail": "page unavailable"}

        selector = self.selectors.get("last_assistant")
        if not selector:
            return {"status": "FAIL", "detail": "selector missing"}

        try:
            locator = self.page.locator(selector)
            text = await self._last_visible_text(locator)
            if text is None:
                return {"status": "FAIL", "detail": "no match"}
            return {"status": "OK", "detail": "matched text"}
        except Exception as exc:
            return {"status": "FAIL", "detail": str(exc)}

    async def _probe_streaming_indicator(self) -> dict[str, str]:
        if self.page is None:
            return {"status": "FAIL", "detail": "page unavailable"}

        selector = self.selectors.get("streaming_indicator")
        if not selector:
            return {"status": "OK", "detail": "fallback mode"}

        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            if count == 0:
                return {"status": "OK", "detail": "configured, not active"}
            if await locator.first.is_visible():
                return {"status": "OK", "detail": "visible"}
            return {"status": "OK", "detail": "configured, hidden"}
        except Exception as exc:
            return {"status": "FAIL", "detail": str(exc)}

    @staticmethod
    def _hash_text(text: str | None) -> str | None:
        if not text:
            return None
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    async def _first_visible_locator(self, selector: str) -> Locator | None:
        if self.page is None:
            return None

        locator = self.page.locator(selector)
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None

    async def _last_visible_text(self, locator: Locator) -> str | None:
        count = await locator.count()
        for index in range(count - 1, -1, -1):
            candidate = locator.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                text = self._normalize_text(await candidate.inner_text())
                if text:
                    return text
            except Exception:
                continue
        return None
