from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from core.logger import JsonlLogger
from core.message import utc_now_iso


class CodexController:
    def __init__(
        self,
        name: str,
        session_dir: str | Path,
        logger: JsonlLogger,
        codex_bin: str = "codex",
    ) -> None:
        self.name = name
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger
        self.codex_bin = codex_bin
        self.resolved_codex_bin: str | None = None
        self.thread_id_path = self.session_dir / "thread_id.txt"

        self.context = None
        self.page = None
        self.ready = False
        self.last_error: str | None = None
        self.last_assistant_timestamp: str | None = None
        self.selector_health = "local-session"

        self.thread_id = self._load_thread_id()
        self._pending_reply: str | None = None
        self._last_emitted_reply: str | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(
        self,
        context: object | None = None,
        url: str | None = None,
        selectors: dict[str, Any] | None = None,
    ) -> None:
        del context, url, selectors

        self.resolved_codex_bin = self._resolve_codex_bin(self.codex_bin)
        if self.resolved_codex_bin is None:
            self.ready = False
            self.last_error = f"Codex binary not found: {self.codex_bin}"
            self.selector_health = "missing-codex-cli"
            raise RuntimeError(self.last_error)

        self.thread_id = self._load_thread_id()
        self.ready = True
        self.last_error = None
        self.selector_health = "local-session"

    async def send(self, text: str) -> bool:
        async with self._lock:
            if self.resolved_codex_bin is None:
                self.ready = False
                self.last_error = f"send: Codex binary not found: {self.codex_bin}"
                self.selector_health = "missing-codex-cli"
                return False
            if self._run_task is not None and not self._run_task.done():
                self.ready = False
                self.last_error = "send: Codex is still processing the previous prompt."
                self.selector_health = "busy"
                return False

            self._run_task = asyncio.create_task(
                self._run_codex(text),
                name=f"co-chat-codex-{self.name}",
            )
            self.ready = True
            self.last_error = None
            self.selector_health = "local-session"
            return True

    async def read_latest(self) -> str | None:
        async with self._lock:
            if self._run_task is not None and self._run_task.done():
                try:
                    await self._run_task
                finally:
                    self._run_task = None

            if self._pending_reply is None:
                return None
            if self._pending_reply == self._last_emitted_reply:
                return None

            reply = self._pending_reply
            self._pending_reply = None
            self._last_emitted_reply = reply
            self.last_assistant_timestamp = utc_now_iso()
            self.last_error = None
            self.ready = True
            self.selector_health = "local-session"
            return reply

    def is_ready(self) -> bool:
        return self.ready

    def status(self) -> dict[str, str]:
        if self._run_task is not None and not self._run_task.done():
            state = "busy"
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
            "page_url": f"codex://{self.thread_id or 'new-session'}",
            "last_assistant_timestamp": self.last_assistant_timestamp or "-",
            "last_error": self.last_error or "-",
            "selector_health": self.selector_health,
        }

    async def probe_selectors(self) -> dict[str, dict[str, str]]:
        detail = "local codex exec session"
        return {
            "input": {"status": "OK", "detail": detail},
            "send_btn": {"status": "OK", "detail": "managed by codex CLI"},
            "last_assistant": {"status": "OK", "detail": "managed by codex CLI"},
            "streaming_indicator": {"status": "OK", "detail": "final reply only"},
        }

    async def _run_codex(self, text: str) -> None:
        output_path = self._next_output_path()
        command = self._command_for(text=text, output_path=output_path)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        thread_id, stdout_reply = self._parse_stdout_events(stdout_text)
        thread_id = thread_id or self.thread_id

        if thread_id:
            self.thread_id = thread_id
            self._save_thread_id(thread_id)

        file_reply = await self._read_output_with_retry(output_path)
        reply = file_reply or stdout_reply

        if process.returncode != 0:
            error_text = stderr_text.strip() or stdout_text.strip() or "Codex command failed."
            self.ready = False
            self.last_error = f"exec: {error_text}"
            self.selector_health = "error during send"
            await self.logger.log_event(
                source=self.name,
                target="hub",
                content=error_text,
                kind="error",
                status="send",
            )
            return

        if not reply:
            self.ready = False
            self.last_error = "exec: Codex returned no reply."
            self.selector_health = "empty-reply"
            await self.logger.log_event(
                source=self.name,
                target="hub",
                content=self._empty_reply_detail(stdout_text, stderr_text, output_path),
                kind="error",
                status="send",
            )
            return

        self._pending_reply = reply
        self.ready = True
        self.last_error = None
        self.selector_health = "local-session"

    def _command_for(self, text: str, output_path: Path) -> list[str]:
        codex_bin = self.resolved_codex_bin or self.codex_bin
        base = [codex_bin, "exec"]
        if self.thread_id:
            return [
                *base,
                "resume",
                "--json",
                "-o",
                str(output_path),
                self.thread_id,
                text,
            ]
        return [
            *base,
            "--json",
            "-o",
            str(output_path),
            text,
        ]

    def _resolve_codex_bin(self, candidate: str) -> str | None:
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return str(candidate_path)

        resolved = shutil.which(candidate)
        if resolved:
            return resolved

        extra_candidates: list[Path] = []

        codex_home = os.getenv("CODEX_HOME")
        if codex_home:
            extra_candidates.append(Path(codex_home) / "bin" / "wsl" / "codex")

        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            windows_profile = Path(userprofile.replace("\\", "/"))
            drive = windows_profile.drive.rstrip(":").lower()
            tail = windows_profile.as_posix().split(":", 1)[-1].lstrip("/")
            if drive:
                extra_candidates.append(
                    Path("/mnt") / drive / tail / ".codex" / "bin" / "wsl" / "codex"
                )

        extra_candidates.extend(Path("/mnt/c/Users").glob("*/.codex/bin/wsl/codex"))

        for path in extra_candidates:
            if path.is_file():
                return str(path)

        return None

    def _load_thread_id(self) -> str | None:
        if not self.thread_id_path.exists():
            return None
        value = self.thread_id_path.read_text(encoding="utf-8").strip()
        return value or None

    def _save_thread_id(self, thread_id: str) -> None:
        self.thread_id_path.write_text(thread_id + "\n", encoding="utf-8")

    def _next_output_path(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            dir=self.session_dir,
            prefix="codex-reply-",
            suffix=".txt",
            encoding="utf-8",
        ) as handle:
            return Path(handle.name)

    def _parse_stdout_events(self, stdout_text: str) -> tuple[str | None, str]:
        thread_id: str | None = None
        latest_reply = ""
        for line in stdout_text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id") or thread_id
                continue

            if event.get("type") != "item.completed":
                continue

            item = event.get("item") or {}
            if item.get("type") != "agent_message":
                continue

            text = str(item.get("text") or "").strip()
            if text:
                latest_reply = text

        return thread_id, latest_reply

    async def _read_output_with_retry(self, output_path: Path) -> str:
        for _ in range(4):
            if output_path.exists():
                reply = output_path.read_text(encoding="utf-8").strip()
                if reply:
                    return reply
            await asyncio.sleep(0.2)
        return ""

    def _empty_reply_detail(
        self,
        stdout_text: str,
        stderr_text: str,
        output_path: Path,
    ) -> str:
        stdout_tail = stdout_text.strip().splitlines()[-3:]
        stderr_tail = stderr_text.strip().splitlines()[-3:]
        details = [
            "Codex returned no reply.",
            f"output_file={output_path}",
        ]
        if stdout_tail:
            details.append("stdout_tail=" + " | ".join(stdout_tail))
        if stderr_tail:
            details.append("stderr_tail=" + " | ".join(stderr_tail))
        return " ".join(details)
