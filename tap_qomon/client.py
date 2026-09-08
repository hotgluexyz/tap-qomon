"""REST client handling, including QomonStream base class."""

from __future__ import annotations

from typing import Any, ClassVar

import requests
from hotglue_etl_exceptions import InvalidCredentialsError
from hotglue_singer_sdk.authenticators import BearerTokenAuthenticator
from hotglue_singer_sdk.streams import RESTStream
from memoization import cached

DEFAULT_API_BASE_URL = "https://incoming.qomon.app"


class QomonStream(RESTStream):
    """Qomon stream class (base)."""

    primary_keys: ClassVar[list[str]] = ["id"]
    replication_key = None

    @property
    def url_base(self) -> str:
        base_url = self.config.get("api_base_url") or DEFAULT_API_BASE_URL
        return base_url.rstrip("/")

    @property
    @cached
    def authenticator(self) -> BearerTokenAuthenticator:
        return BearerTokenAuthenticator(stream=self, token=self.config["api_key"])

    @property
    def http_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def get_url(self, context: dict | None) -> str:
        return f"{self.url_base}/{self.path.lstrip('/')}"

    def validate_response(self, response: requests.Response) -> None:
        """Raise an exception if the response is not valid."""
        if response.status_code in {401, 403}:
            raise InvalidCredentialsError(response.text or response.reason)
        super().validate_response(response)

    @staticmethod
    def unwrap_data(payload: Any, *keys: str) -> Any:
        """Return nested data from a Qomon ``{"status": ..., "data": {...}}`` envelope."""
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def request_json(self, method: str, url: str, payload: dict | None = None) -> Any:
        """Run an authenticated one-off request outside the record pagination loop."""
        prepared_request = self.build_prepared_request(
            method,
            url,
            headers=self.http_headers,
            json=payload,
        )
        decorated_request = self.request_decorator(self._request)
        response: requests.Response = decorated_request(prepared_request, None)
        return response.json()
