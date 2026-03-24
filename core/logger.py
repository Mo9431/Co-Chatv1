from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from core.message import Message


class JsonlLogger:
    def __init__(self, log_dir: str, filename: str = "chat.jsonl") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / filename
        self._lock = asyncio.Lock()

    async def log_message(self, message: Message, status: str = "ok") -> None:
        payload = message.to_dict()
        payload["status"] = status
        await self._write(payload)

    async def log_event(
        self,
        *,
        source: str,
        target: str,
        content: str,
        kind: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": Message(source=source, target=target, content=content, kind="system").timestamp,
            "source": source,
            "target": target,
            "content": content,
            "kind": kind,
            "status": status,
        }
        if metadata:
            payload["metadata"] = metadata
        await self._write(payload)

    async def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            await asyncio.to_thread(self._append_line, line)

    def _append_line(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
