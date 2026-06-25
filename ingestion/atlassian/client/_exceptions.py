from typing import Any


class AtlassianException(Exception):
    """Base exception for all exceptions raised by the Atlassian client."""


class NetworkException(AtlassianException):
    """Raised when a network error occurs."""

    def __init__(self, message: str | None = None):
        self.message = message or "Network error occurred"
        super().__init__(self.message)


class TimedOutException(NetworkException):
    """Raised when a request times out."""

    def __init__(self, message: str | None = None):
        self.message = message or "Timed out"
        super().__init__(self.message)


class HTTPException(AtlassianException):
    """Raised for non-success HTTP responses (4xx/5xx)."""

    def __init__(
            self,
            status_code: int,
            message: str | None = None,
            *,
            url: str | None = None,
            method: str | None = None,
            response_body: Any = None,
            error_messages: list[str] | None = None,
    ):
        self.status_code = status_code
        self.url = url
        self.method = method
        self.response_body = response_body
        self.error_messages = error_messages or []
        self.message = message or f"HTTP {status_code}"
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [self.message]
        if self.method and self.url:
            parts.append(f"{self.method} {self.url}")
        if self.error_messages:
            parts.append("; ".join(self.error_messages))
        return " | ".join(parts)


class BadRequestException(HTTPException):
    """400."""


class UnauthorizedException(HTTPException):
    """401."""


class ForbiddenException(HTTPException):
    """403."""


class NotFoundException(HTTPException):
    """404."""


class ConflictException(HTTPException):
    """409."""


class RateLimitedException(HTTPException):
    """429 (returned only when retries are exhausted)."""


class ServerErrorException(HTTPException):
    """5xx."""


_STATUS_TO_EXCEPTION: dict[int, type[HTTPException]] = {
    400: BadRequestException,
    401: UnauthorizedException,
    403: ForbiddenException,
    404: NotFoundException,
    409: ConflictException,
    429: RateLimitedException,
}


def exception_for_status(status_code: int) -> type[HTTPException]:
    if status_code in _STATUS_TO_EXCEPTION:
        return _STATUS_TO_EXCEPTION[status_code]
    if 500 <= status_code < 600:
        return ServerErrorException
    return HTTPException
