from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ResourceScheduler:
    def __init__(self, concurrency: int = 1, queue_limit: int = 8) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._queue_limit = queue_limit
        self._waiting = 0
        self._active = 0

    @property
    def status(self) -> dict[str, int]:
        return {"active": self._active, "waiting": self._waiting, "queue_limit": self._queue_limit}

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self._waiting >= self._queue_limit:
            raise RuntimeError("The local inference queue is full")
        self._waiting += 1
        try:
            await self._semaphore.acquire()
        finally:
            self._waiting -= 1
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1
            self._semaphore.release()
