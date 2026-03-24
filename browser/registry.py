from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserType

from browser.controller import AIController
from core.logger import JsonlLogger
from core.state import RuntimeState


async def build_controllers(
    browser_type: BrowserType,
    session_root: str,
    headless: bool,
    providers: list[str],
    urls: dict[str, str],
    selector_map: dict[str, dict[str, str]],
    logger: JsonlLogger,
    state: RuntimeState,
    browser_args: list[str],
    action_timeout_ms: int,
    navigation_timeout_ms: int,
) -> dict[str, AIController]:
    controllers: dict[str, AIController] = {}
    root_path = Path(session_root)
    root_path.mkdir(parents=True, exist_ok=True)

    for provider in providers:
        url = urls.get(provider)
        selectors = selector_map.get(provider)

        if not url or not selectors:
            error_text = f"Provider '{provider}' is missing URL or selectors."
            state.record_error(error_text)
            state.set_controller_status(provider, f"error: {error_text}")
            await logger.log_event(
                source="registry",
                target=provider,
                content=error_text,
                kind="error",
                status="config-error",
            )
            continue

        controller = AIController(
            name=provider,
            url=url,
            selectors=selectors,
            logger=logger,
        )
        controllers[provider] = controller
        state.set_controller_status(provider, "starting")

        try:
            profile_dir = root_path / provider
            profile_dir.mkdir(parents=True, exist_ok=True)

            context = await browser_type.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=headless,
                args=browser_args,
                no_viewport=True,
            )
            context.set_default_timeout(action_timeout_ms)
            context.set_default_navigation_timeout(navigation_timeout_ms)

            await controller.start(context=context)
            state.set_controller_status(provider, "ready")
            await logger.log_event(
                source="registry",
                target=provider,
                content=f"{provider} started on {url} with profile {profile_dir}",
                kind="system",
                status="ready",
            )
        except Exception as exc:
            state.record_error(f"{provider}: {exc}")
            state.set_controller_status(provider, f"error: {exc}")
            await logger.log_event(
                source="registry",
                target=provider,
                content=str(exc),
                kind="error",
                status="start-error",
            )

    return controllers
