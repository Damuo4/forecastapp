import time
from typing import Any

import httpx


class SecEdgarClientError(RuntimeError):
    pass


class SecEdgarClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_seconds: float = 20.0,
        min_interval_seconds: float = 0.2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise SecEdgarClientError("SEC_USER_AGENT is required for SEC EDGAR requests.")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }

    def _throttle(self) -> None:
        now = time.monotonic()
        remaining = self.min_interval_seconds - (now - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def get_json(self, path: str) -> dict[str, Any]:
        self._throttle()
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self._client.get(url, headers=self._headers)
        if response.status_code != 200:
            raise SecEdgarClientError(
                f"SEC request failed ({response.status_code}) for path: {path}"
            )
        return response.json()

    def get_submissions(self, cik_padded_10: str) -> dict[str, Any]:
        return self.get_json(f"submissions/CIK{cik_padded_10}.json")

    def get_company_facts(self, cik_padded_10: str) -> dict[str, Any]:
        return self.get_json(f"api/xbrl/companyfacts/CIK{cik_padded_10}.json")
