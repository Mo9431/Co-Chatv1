from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

MessageKind = Literal["user", "assistant", "system", "route", "error"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Message:
    source: str
    target: str
    content: str
    timestamp: str = field(default_factory=utc_now_iso)
    kind: MessageKind = "user"
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)
