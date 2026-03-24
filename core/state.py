from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

Route = tuple[str, str]


@dataclass
class RuntimeState:
    max_auto_rounds: int
    active_routes: set[Route] = field(default_factory=set)
    loop_counters: dict[Route, int] = field(default_factory=dict)
    controller_statuses: dict[str, str] = field(default_factory=dict)
    recent_errors: deque[str] = field(default_factory=lambda: deque(maxlen=20))

    def add_route(self, source: str, target: str) -> bool:
        route = (source, target)
        if route in self.active_routes:
            return False
        self.active_routes.add(route)
        self.loop_counters[route] = 0
        return True

    def remove_route(self, source: str, target: str) -> bool:
        route = (source, target)
        if route not in self.active_routes:
            return False
        self.active_routes.remove(route)
        self.loop_counters.pop(route, None)
        return True

    def list_routes(self) -> list[Route]:
        return sorted(self.active_routes)

    def increment_loop(self, source: str, target: str) -> int:
        route = (source, target)
        current = self.loop_counters.get(route, 0) + 1
        self.loop_counters[route] = current
        return current

    def get_loop_count(self, source: str, target: str) -> int:
        return self.loop_counters.get((source, target), 0)

    def set_controller_status(self, name: str, status: str) -> None:
        self.controller_statuses[name] = status

    def record_error(self, error_text: str) -> None:
        self.recent_errors.appendleft(error_text)
