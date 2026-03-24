from __future__ import annotations

import asyncio
import sys

from core.message import Message
from router import Router


class CLI:
    def __init__(self, router: Router) -> None:
        self.router = router
        self.router.register_listener(self._on_router_message)
        self._stdout_lock = asyncio.Lock()

    async def run(self) -> None:
        await self._write_line("Co-Chat CLI ready. Type 'help' for commands.")

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        try:
            while not self.router.shutting_down():
                await self._write_prompt()
                raw = await reader.readline()
                if not raw:
                    self.router.request_shutdown()
                    break

                line = raw.decode().strip()
                if not line:
                    continue

                response = await self.router.handle_command(line, interface="cli")
                if response:
                    await self._write_line(response)
        finally:
            transport.close()

    async def _on_router_message(self, message: Message) -> None:
        prefix = f"[{message.kind}:{message.source}]"
        await self._write_line(f"{prefix} {message.content}")

    async def _write_prompt(self) -> None:
        async with self._stdout_lock:
            print("co-chat> ", end="", flush=True)

    async def _write_line(self, text: str) -> None:
        async with self._stdout_lock:
            print(text, flush=True)
