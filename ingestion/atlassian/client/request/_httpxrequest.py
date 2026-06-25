import logging
from typing import Any

import httpx

from ingestion.atlassian.client.request._baserequest import BaseRequest
from ingestion.atlassian.client.request._transport import RetryAfterTransport
from ingestion.atlassian.client._exceptions import (
    TimedOutException,
    NetworkException,
    exception_for_status,
)

logger = logging.getLogger(__name__)


class HttpxRequest(BaseRequest):
    def __init__(
            self,
            connection_pool_size: int = 256,
            read_timeout: float | None = None,
            write_timeout: float | None = None,
            connect_timeout: float | None = None,
            pool_timeout: float | None = None,
            max_retries: int = 3,
            retry_on_rate_limit: bool = True,
            rate_limit_max_wait: float = 60.0,
            httpx_kwargs: dict[str, Any] | None = None
    ):
        timeout = httpx.Timeout(
            read=read_timeout,
            write=write_timeout,
            connect=connect_timeout,
            pool=pool_timeout,
        )
        limits = httpx.Limits(
            max_connections=connection_pool_size,
        )
        inner_transport = httpx.AsyncHTTPTransport(
            retries=max_retries,
            limits=limits,
        )
        transport = (
            RetryAfterTransport(
                inner_transport,
                max_retries=max_retries,
                max_wait=rate_limit_max_wait
            )
            if retry_on_rate_limit else
            inner_transport
        )
        self._client_kwargs = {
            "timeout": timeout,
            "transport": transport,
            **(httpx_kwargs or {}),
        }
        self._client: httpx.AsyncClient = self._build_client()

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**self._client_kwargs)

    async def initialize(self):
        if self._client and self._client.is_closed:
            self._client = self._build_client()

    async def shutdown(self):
        if self._client and self._client.is_closed:
            logger.debug("HTTP Client is already closed.")
            return
        await self._client.aclose()

    async def do_request(  # type: ignore[override]
            self,
            method: str,
            path: str,
            read_timeout: float | None = None,
            write_timeout: float | None = None,
            connect_timeout: float | None = None,
            pool_timeout: float | None = None,
            raise_for_status: bool = True,
            **kwargs
    ) -> httpx.Response:
        timeout = httpx.Timeout(
            read=read_timeout,
            write=write_timeout,
            connect=connect_timeout,
            pool=pool_timeout,
        )
        try:
            response = await self._client.request(method, path, timeout=timeout, **kwargs)
        except httpx.TimeoutException as e:
            raise TimedOutException(str(e)) from e
        except httpx.HTTPError as e:
            raise NetworkException(str(e)) from e
        if raise_for_status and response.status_code >= 400:
            self._raise_http_error(response)
        return response

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        body: Any = None
        error_messages: list[str] = []
        try:
            body = response.json()
            if isinstance(body, dict):
                msgs = body.get("errorMessages")
                if isinstance(msgs, list):
                    error_messages.extend(str(m) for m in msgs)
                errors = body.get("errors")
                if isinstance(errors, dict):
                    error_messages.extend(f"{k}: {v}" for k, v in errors.items())
        except ValueError:
            body = response.text
        exc_cls = exception_for_status(response.status_code)
        raise exc_cls(
            status_code=response.status_code,
            message=f"HTTP {response.status_code} {response.reason_phrase}",
            url=str(response.request.url) if response.request else None,
            method=response.request.method if response.request else None,
            response_body=body,
            error_messages=error_messages,
        )
