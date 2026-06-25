import asyncio
import httpx
import logging
from datetime import datetime, timezone
from dataclasses import dataclass


logger = logging.getLogger(__name__)

@dataclass
class RateLimitInfo:
    retry_after_seconds: float
    limit: int | None
    remaining: int | None
    reset_at: datetime | None
    reason: str | None

    def __str__(self):
        return (
            f"RateLimit — reason={self.reason}, "
            f"remaining={self.remaining}/{self.limit}, "
            f"reset={self.reset_at.isoformat() if self.reset_at else 'N/A'}, "
            f"wait={self.retry_after_seconds:.1f}s"
        )


def parse_rate_limit_headers(response: httpx.Response, max_wait: float = 60.0) -> RateLimitInfo:
    retry_after_seconds = 1.0
    retry_after_raw = response.headers.get("Retry-After")
    if retry_after_raw:
        try:
            retry_after_seconds = max(0.0, float(retry_after_raw))
        except ValueError:
            retry_after_seconds = 1.0

    reset_at = None
    reset_raw: str = response.headers.get("X-RateLimit-Reset")
    if reset_raw:
        try:
            reset_at = datetime.fromisoformat(reset_raw.replace("Z", "+00:00"))
        except ValueError:
            pass

    if not retry_after_raw and reset_at:
        delta = (reset_at - datetime.now(tz=timezone.utc)).total_seconds()
        retry_after_seconds = max(0.0, delta)

    retry_after_seconds = min(retry_after_seconds, max_wait)

    limit_raw = response.headers.get("X-RateLimit-Limit")
    remaining_raw = response.headers.get("X-RateLimit-Remaining")

    return RateLimitInfo(
        retry_after_seconds=retry_after_seconds,
        limit=int(limit_raw) if limit_raw else None,
        remaining=int(remaining_raw) if remaining_raw else None,
        reset_at=reset_at,
        reason=response.headers.get("RateLimit-Reason"),
    )


class RetryAfterTransport(httpx.AsyncBaseTransport):
    RETRYABLE_STATUSES = {429, 503}

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        max_retries: int = 3,
        max_wait: float = 60.0,
    ):
        self.wrapped = wrapped
        self.max_retries = max_retries
        self.max_wait = max_wait

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.wrapped.handle_async_request(request)
        if response.status_code not in self.RETRYABLE_STATUSES:
            return response

        for attempt in range(self.max_retries):
            rate_limit = parse_rate_limit_headers(response, max_wait=self.max_wait)
            logger.debug(f"[Attempt {attempt + 1}/{self.max_retries}] {rate_limit}")

            await response.aclose()
            await asyncio.sleep(rate_limit.retry_after_seconds)

            response = await self.wrapped.handle_async_request(request)
            if response.status_code not in self.RETRYABLE_STATUSES:
                return response

        logger.warning(
            f"Rate limit exhausted after {self.max_retries} retries. "
            f"url={request.url}, status={response.status_code}"
        )
        return response

    async def aclose(self) -> None:
        await self.wrapped.aclose()
