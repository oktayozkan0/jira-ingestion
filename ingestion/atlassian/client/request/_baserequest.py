import abc
from types import TracebackType
from logging import getLogger

import httpx


logger = getLogger(__name__)

class BaseRequest(abc.ABC):
    async def __aenter__(self):
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None
    ):
        await self.shutdown()

    @abc.abstractmethod
    async def initialize(self):
        """Initialize resources used by this class. Must be implemented by a subclass."""

    @abc.abstractmethod
    async def shutdown(self):
        """Clean up resources used by this class. Must be implemented by a subclass."""

    @abc.abstractmethod
    async def do_request(
            self,
            method: str,
            path: str,
            raise_for_status: bool = True,
            **kwargs
    ) -> httpx.Response:
        """Perform the actual HTTP request. Must be implemented by a subclass."""
