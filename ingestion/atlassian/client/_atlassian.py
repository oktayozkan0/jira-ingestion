from typing import Any

import httpx

from ingestion.atlassian.client.request._httpxrequest import HttpxRequest


class Atlassian:
    def __init__(
            self,
            base_url: str,
            email: str,
            api_token: str,
            *,
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
        self.base_url = base_url
        self.email = email
        self.api_token = api_token
        auth = httpx.BasicAuth(email, api_token)
        self._request: HttpxRequest = HttpxRequest(
            connection_pool_size=connection_pool_size,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            max_retries=max_retries,
            retry_on_rate_limit=retry_on_rate_limit,
            rate_limit_max_wait=rate_limit_max_wait,
            httpx_kwargs={
                "auth": auth,
                "base_url": base_url,
                **(httpx_kwargs or {}),
            }
        )

    async def __aenter__(self):
        try:
            await self._request.initialize()
        except Exception:
            await self._request.shutdown()
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._request.shutdown()

    async def _get(self, path: str, **kwargs) -> Any:
        response = await self._request.do_request("GET", path, **kwargs)
        return response.json() if response.content else None

    async def _post(self, path: str, json: Any | None = None, **kwargs) -> Any:
        """POST used only for read-style endpoints (e.g. JQL search, worklog bulk fetch)."""
        response = await self._request.do_request("POST", path, json=json, **kwargs)
        return response.json() if response.content else None

    async def get_myself(self) -> dict[str, Any]:
        return await self._get("/rest/api/3/myself")
