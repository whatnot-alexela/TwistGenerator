"""One generation at a time per user.

Without this, holding down the button starts several generations at once: each
passes the quota check before any of them has been charged, so the owner pays
for all of them and the user is charged for one.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class SingleFlight:
    """Per-user locks, created on demand."""

    def __init__(self) -> None:
        self._busy: set[int] = set()
        self._guard = asyncio.Lock()

    async def acquire(self, user_id: int) -> bool:
        async with self._guard:
            if user_id in self._busy:
                return False
            self._busy.add(user_id)
            return True

    async def release(self, user_id: int) -> None:
        async with self._guard:
            self._busy.discard(user_id)

    @asynccontextmanager
    async def hold(self, user_id: int) -> AsyncIterator[bool]:
        """Yields whether the lock was taken; always releases what it took."""
        acquired = await self.acquire(user_id)
        try:
            yield acquired
        finally:
            if acquired:
                await self.release(user_id)
