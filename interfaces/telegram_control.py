from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.types import Message as TelegramMessage

from core.message import Message
from router import Router


class TelegramControl:
    def __init__(self, router: Router, bot_token: str, chat_id: int) -> None:
        self.router = router
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self.poll_task: asyncio.Task[None] | None = None
        self.last_chat_id: int | None = chat_id if chat_id else None
        self.router.register_listener(self._on_router_message)

    async def start(self) -> None:
        if not self.bot_token:
            raise RuntimeError("ENABLE_TELEGRAM is true but BOT_TOKEN is empty.")

        self.bot = Bot(self.bot_token)
        await self.bot.set_my_commands(
            [
                BotCommand(command="help", description="Show available Co-Chat commands"),
                BotCommand(command="status", description="Show provider status"),
                BotCommand(command="probe", description="Probe selector health"),
                BotCommand(command="routes", description="List active relay routes"),
            ]
        )
        self.dispatcher = Dispatcher()
        self.dispatcher.message.register(self._handle_message)
        self.poll_task = asyncio.create_task(
            self.dispatcher.start_polling(self.bot, handle_signals=False),
            name="co-chat-telegram",
        )

    async def stop(self) -> None:
        if self.poll_task is not None:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

        if self.bot is not None:
            await self.bot.session.close()

    async def _handle_message(self, message: TelegramMessage) -> None:
        if not message.text:
            return
        if self.chat_id and message.chat.id != self.chat_id:
            return

        self.last_chat_id = message.chat.id
        reply = await self.router.handle_command(message.text, interface="telegram")
        if reply and self.bot is not None:
            await self.bot.send_message(chat_id=message.chat.id, text=reply)

    async def _on_router_message(self, message: Message) -> None:
        target_chat = self.chat_id or self.last_chat_id
        if self.bot is None or target_chat is None:
            return

        text = f"[{message.kind}:{message.source}] {message.content}"
        await self.bot.send_message(chat_id=target_chat, text=text)
