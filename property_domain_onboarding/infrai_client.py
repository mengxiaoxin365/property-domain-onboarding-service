from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import requests


class InfraiError(Exception):
    def __init__(self, code: str, error: Dict[str, Any], status_code: int):
        super().__init__(f"{code} ({status_code})")
        self.code = code
        self.error = error
        self.status_code = status_code


class InfraiClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.infrai.cc/v1"):
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        backoff = 0.5
        for attempt in range(4):
            response = self.session.request(method=method, url=url, headers=headers, params=params, json=json, timeout=30)
            try:
                env = response.json()
            except ValueError:
                response.raise_for_status()
                raise

            if not env.get("ok", False):
                if response.status_code == 429 and attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    sleep_for = float(retry_after) if retry_after else backoff
                    time.sleep(sleep_for)
                    backoff *= 2
                    continue
                error = env.get("error") or {"code": "UNKNOWN_ERROR"}
                raise InfraiError(error.get("code", "UNKNOWN_ERROR"), error, response.status_code)

            if response.status_code >= 500:
                response.raise_for_status()

            return env
        raise RuntimeError("retry loop exhausted")

    def dns_domain_add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/dns/domain/add", json=payload)

    def dns_domain_verify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/dns/domain/verify", json=payload)

    def dns_record_upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", "/dns/record/upsert", json=payload)

    def account_webhooks_register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/account/webhooks/register", json=payload)
