"""进程内事件总线：领域事件 → SSE 转发的桥。

事件不持久化；订阅者按 topic 过滤；队列满则丢弃（日志流允许丢帧，不阻塞领域逻辑）。
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

DEFAULT_QUEUE_SIZE = 2000


@dataclass
class Subscription:
    topics: set[str]
    queue: asyncio.Queue[tuple[str, dict[str, Any]]]
    maxsize: int = DEFAULT_QUEUE_SIZE


@dataclass
class EventBus:
    subscribers: list[Subscription] = field(default_factory=list)

    def subscribe(self, topics: set[str]) -> Subscription:
        sub = Subscription(topics=topics, queue=asyncio.Queue(maxsize=DEFAULT_QUEUE_SIZE))
        self.subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self.subscribers:
            self.subscribers.remove(sub)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        for sub in self.subscribers:
            if sub.topics and topic not in sub.topics:
                continue
            # 丢帧保护：慢消费者不得拖垮领域逻辑
            with contextlib.suppress(asyncio.QueueFull):
                sub.queue.put_nowait((topic, payload))
