from __future__ import annotations

import asyncio
from typing import Any
from typing import Awaitable, Callable

from core.logger import JsonlLogger
from core.message import Message
from core.state import RuntimeState

EventListener = Callable[[Message], Awaitable[None] | None]


class Router:
    def __init__(
        self,
        controllers: dict[str, Any],
        logger: JsonlLogger,
        state: RuntimeState,
        poll_interval: float,
    ) -> None:
        self.controllers = controllers
        self.logger = logger
        self.state = state
        self.poll_interval = poll_interval
        self.shutdown_event = asyncio.Event()
        self._listeners: list[EventListener] = []

    def register_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def request_shutdown(self) -> None:
        self.shutdown_event.set()

    def shutting_down(self) -> bool:
        return self.shutdown_event.is_set()

    def start_monitoring(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.monitor_replies(), name="co-chat-monitor")

    async def monitor_replies(self) -> None:
        while not self.shutting_down():
            for name, controller in self.controllers.items():
                try:
                    reply = await controller.read_latest()
                    self.state.set_controller_status(name, controller.status()["state"])
                    if reply is None:
                        continue

                    message = Message(
                        source=name,
                        target="hub",
                        content=reply,
                        kind="assistant",
                    )
                    await self.logger.log_message(message, status="received")
                    await self._emit(message)
                    await self._forward_reply(source=name, text=reply)
                except Exception as exc:
                    error_text = f"{name}: {exc}"
                    self.state.record_error(error_text)
                    self.state.set_controller_status(name, f"error: {exc}")
                    await self.logger.log_event(
                        source=name,
                        target="hub",
                        content=str(exc),
                        kind="error",
                        status="monitor-error",
                    )

            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=self.poll_interval,
                )
            except asyncio.TimeoutError:
                continue

    async def send_to_target(
        self,
        target: str,
        text: str,
        *,
        source: str = "user",
        kind: str = "user",
    ) -> bool:
        controller = self.controllers.get(target)
        if controller is None:
            await self._emit_system(f"Unknown target: {target}")
            return False

        ok = await controller.send(text)
        status = "sent" if ok else "send-error"
        if ok:
            self.state.set_controller_status(target, controller.status()["state"])
        else:
            self.state.set_controller_status(target, controller.status()["state"])
            if controller.last_error:
                self.state.record_error(f"{target}: {controller.last_error}")

        await self.logger.log_message(
            Message(source=source, target=target, content=text, kind=kind),
            status=status,
        )
        return ok

    async def send_to_all(self, text: str) -> tuple[int, int]:
        return await self.send_to_many(
            targets=self.controllers.keys(),
            text=text,
        )

    async def send_to_many(
        self,
        targets,
        text: str,
        *,
        source: str = "user",
        kind: str = "user",
    ) -> tuple[int, int]:
        success = 0
        failure = 0
        for target in targets:
            if await self.send_to_target(target, text, source=source, kind=kind):
                success += 1
            else:
                failure += 1
        return success, failure

    async def add_route(self, source: str, target: str) -> str:
        source = source.lower()
        target = target.lower()

        if source == target:
            return "Route source and target must be different."
        if source not in self.controllers:
            return f"Unknown source: {source}"
        if target not in self.controllers:
            return f"Unknown target: {target}"

        added = self.state.add_route(source, target)
        if not added:
            return f"Route already active: {source} -> {target}"

        await self.logger.log_event(
            source=source,
            target=target,
            content=f"Relay enabled for {source} -> {target}",
            kind="route",
            status="enabled",
        )
        return f"Route enabled: {source} -> {target}"

    async def remove_route(self, source: str, target: str) -> str:
        source = source.lower()
        target = target.lower()
        removed = self.state.remove_route(source, target)
        if not removed:
            return f"Route not active: {source} -> {target}"

        await self.logger.log_event(
            source=source,
            target=target,
            content=f"Relay disabled for {source} -> {target}",
            kind="route",
            status="disabled",
        )
        return f"Route disabled: {source} -> {target}"

    def routes_text(self) -> str:
        routes = self.state.list_routes()
        if not routes:
            return "No active routes."

        lines = ["Active routes:"]
        for source, target in routes:
            current = self.state.get_loop_count(source, target)
            lines.append(
                f"- {source} -> {target} ({current}/{self.state.max_auto_rounds})"
            )
        return "\n".join(lines)

    def status_text(self) -> str:
        lines = ["Providers:"]
        for name in sorted(self.controllers):
            info = self.controllers[name].status()
            lines.append(
                f"- {name} | ready={info['ready']} | state={info['state']} "
                f"| url={info['page_url']} | last_reply={info['last_assistant_timestamp']} "
                f"| selector={info['selector_health']} | error={info['last_error']}"
            )

        if self.state.recent_errors:
            lines.append("Recent errors:")
            for error in self.state.recent_errors:
                lines.append(f"- {error}")

        return "\n".join(lines)

    async def probe_text(self) -> str:
        lines = ["Selector probe:"]
        for name in sorted(self.controllers):
            results = await self.controllers[name].probe_selectors()
            lines.append(f"- {name}")
            for selector_name in ("input", "send_btn", "last_assistant", "streaming_indicator"):
                result = results[selector_name]
                lines.append(
                    f"  {selector_name}: {result['status']} ({result['detail']})"
                )
        return "\n".join(lines)

    async def handle_command(self, line: str, interface: str = "cli") -> str:
        text = line.strip()
        if not text:
            return ""

        command, _, remainder = text.partition(" ")
        command = self._normalize_command(command)
        payload = remainder.strip()

        if command in self.controllers:
            if not payload:
                return f"Usage: {command} <text>"
            ok = await self.send_to_target(command, payload)
            return (
                f"[{interface}] sent to {command}"
                if ok
                else f"[{interface}] failed to send to {command}"
            )

        if command == "all":
            if not payload:
                return "Usage: all <text>"
            success, failure = await self.send_to_all(payload)
            return f"[{interface}] broadcast finished: {success} ok, {failure} failed"

        if command == "compare":
            if not payload:
                return "Usage: compare <prompt>"
            await self.logger.log_event(
                source="compare",
                target="all",
                content=payload,
                kind="system",
                status="compare-start",
            )
            success, failure = await self.send_to_many(
                targets=sorted(self.controllers),
                text=payload,
                source="compare",
                kind="user",
            )
            return (
                f"[{interface}] compare sent: {success} ok, {failure} failed. "
                "Replies will print separately as they arrive."
            )

        if command == "status":
            return self.status_text()

        if command == "probe":
            return await self.probe_text()

        if command == "routes":
            return self.routes_text()

        if command == "relay":
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                return "Usage: relay <source> <target>"
            _, source, target = parts
            return await self.add_route(source, target)

        if command == "stoproute":
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                return "Usage: stoproute <source> <target>"
            _, source, target = parts
            return await self.remove_route(source, target)

        if command in {"quit", "exit"}:
            self.request_shutdown()
            return "Shutting down."

        if command in {"help", "start"}:
            return self.help_text()

        return f"Unknown command: {command}. Type 'help' for commands."

    def help_text(self) -> str:
        provider_commands = ", ".join(
            f"{name} <text>" for name in sorted(self.controllers)
        )
        return (
            f"Commands: {provider_commands}, all <text>, compare <prompt>, "
            "status, probe, routes, relay <source> <target>, "
            "stoproute <source> <target>, quit"
        )

    @staticmethod
    def _normalize_command(command: str) -> str:
        normalized = command.strip().lower()
        if normalized.startswith("/"):
            normalized = normalized[1:]
        if "@" in normalized:
            normalized = normalized.split("@", 1)[0]
        return normalized

    async def _forward_reply(self, source: str, text: str) -> None:
        for route_source, route_target in self.state.list_routes():
            if route_source != source:
                continue
            if self.state.get_loop_count(route_source, route_target) >= self.state.max_auto_rounds:
                continue

            forwarded_text = f"Reply from {source}:\n\n{text}"
            ok = await self.send_to_target(
                route_target,
                forwarded_text,
                source=source,
                kind="route",
            )
            current = self.state.increment_loop(route_source, route_target)

            if ok:
                await self.logger.log_event(
                    source=route_source,
                    target=route_target,
                    content=f"Forwarded reply round {current}/{self.state.max_auto_rounds}",
                    kind="route",
                    status="forwarded",
                )
            else:
                await self.logger.log_event(
                    source=route_source,
                    target=route_target,
                    content=f"Forward failed at round {current}/{self.state.max_auto_rounds}",
                    kind="route",
                    status="forward-error",
                )

            if current >= self.state.max_auto_rounds:
                await self._emit_system(
                    f"Route limit reached for {route_source} -> {route_target}. "
                    "Use stoproute and relay again to reset it."
                )

    async def _emit(self, message: Message) -> None:
        for listener in self._listeners:
            try:
                maybe_awaitable = listener(message)
                if maybe_awaitable is not None:
                    await maybe_awaitable
            except Exception as exc:
                error_text = f"Listener failure: {exc}"
                self.state.record_error(error_text)
                await self.logger.log_event(
                    source="router",
                    target="listener",
                    content=str(exc),
                    kind="error",
                    status="listener-error",
                )

    async def _emit_system(self, text: str) -> None:
        message = Message(
            source="system",
            target="hub",
            content=text,
            kind="system",
        )
        await self.logger.log_message(message, status="info")
        await self._emit(message)
