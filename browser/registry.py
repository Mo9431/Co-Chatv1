from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, BrowserType

from browser.controller import AIController
from browser.codex_controller import CodexController
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
    preferred_channel: str,
    preferred_executable_path: str,
    codex_bin: str,
) -> dict[str, Any]:
    controllers: dict[str, Any] = {}
    root_path = Path(session_root)
    root_path.mkdir(parents=True, exist_ok=True)

    for provider in providers:
        if provider == "codex":
            controller = CodexController(
                name=provider,
                session_dir=root_path / provider,
                logger=logger,
                codex_bin=codex_bin,
            )
            controllers[provider] = controller
            state.set_controller_status(provider, "starting")

            try:
                await controller.start()
                state.set_controller_status(provider, "ready")
                await logger.log_event(
                    source="registry",
                    target=provider,
                    content=(
                        f"{provider} local session ready in {root_path / provider} "
                        f"using binary {codex_bin}"
                    ),
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
            continue

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

            context, launch_label = await _launch_provider_context(
                browser_type=browser_type,
                profile_dir=profile_dir,
                headless=headless,
                browser_args=browser_args,
                preferred_channel=preferred_channel,
                preferred_executable_path=preferred_executable_path,
            )
            context.set_default_timeout(action_timeout_ms)
            context.set_default_navigation_timeout(navigation_timeout_ms)

            await controller.start(context=context)
            state.set_controller_status(provider, "ready")
            await logger.log_event(
                source="registry",
                target=provider,
                content=(
                    f"{provider} started on {url} with profile {profile_dir} "
                    f"using {launch_label}"
                ),
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


async def _launch_provider_context(
    *,
    browser_type: BrowserType,
    profile_dir: Path,
    headless: bool,
    browser_args: list[str],
    preferred_channel: str,
    preferred_executable_path: str,
) -> tuple[BrowserContext, str]:
    base_kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "args": browser_args,
        "viewport": None,
    }

    attempts: list[tuple[str, dict[str, object]]] = []
    if preferred_channel:
        attempts.append(
            (
                f"channel={preferred_channel}",
                {**base_kwargs, "channel": preferred_channel},
            )
        )

    if preferred_executable_path and Path(preferred_executable_path).exists():
        attempts.append(
            (
                f"executable_path={preferred_executable_path}",
                {**base_kwargs, "executable_path": preferred_executable_path},
            )
        )

    attempts.append(("playwright-default", base_kwargs))

    errors: list[str] = []
    for label, kwargs in attempts:
        try:
            context = await browser_type.launch_persistent_context(**kwargs)
            if label == "playwright-default" and errors:
                return context, f"{label} (after real-Chrome attempts failed)"
            return context, label
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    raise RuntimeError("All browser launch attempts failed: " + " | ".join(errors))
