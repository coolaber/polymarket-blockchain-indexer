"""Minimal read-only JSON-RPC client for Polygon log queries."""

from __future__ import annotations

import json
import ssl
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RpcError(RuntimeError):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code

    @property
    def range_too_large(self) -> bool:
        value = str(self).lower()
        return self.code == -32005 or any(
            phrase in value for phrase in ("too many results", "block range", "response size", "query limit")
        )


class PolygonRpc:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 30,
        retries: int = 4,
        open_url: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("RPC URL must begin with https:// or http://")
        if timeout <= 0 or retries < 0:
            raise ValueError("timeout must be positive and retries non-negative")
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.open_url = open_url
        self.sleep = sleep

    def call(self, method: str, params: list[Any]) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        request = Request(
            self.url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": "polymarket-blockchain-indexer/1.0"},
            method="POST",
        )
        for attempt in range(self.retries + 1):
            try:
                with self.open_url(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise RpcError("RPC response is not an object")
                error = payload.get("error")
                if error is not None:
                    if not isinstance(error, dict):
                        raise RpcError("RPC returned a malformed error")
                    code = error.get("code")
                    message = str(error.get("message", "unknown error"))[:160]
                    raise RpcError(f"RPC {method} error: {message}", code if isinstance(code, int) else None)
                if "result" not in payload:
                    raise RpcError("RPC response has no result")
                return payload["result"]
            except HTTPError as error:
                if error.code != 429 and not 500 <= error.code <= 599:
                    raise RpcError(f"RPC HTTP {error.code}") from error
                failure = error
            except URLError as error:
                if isinstance(error.reason, ssl.SSLCertVerificationError):
                    raise RpcError(
                        "RPC TLS certificate verification failed; check the endpoint certificate and hostname"
                    ) from error
                failure = error
            except (TimeoutError, OSError) as error:
                failure = error
            except (ValueError, UnicodeError) as error:
                raise RpcError("RPC returned invalid JSON") from error
            if attempt < self.retries:
                self.sleep(min(0.5 * 2**attempt, 8.0))
        raise RpcError(f"RPC transport failed after {self.retries + 1} attempt(s)") from failure

    def chain_id(self) -> int:
        return _parse_quantity(self.call("eth_chainId", []), "chain ID")

    def latest_block(self) -> int:
        return _parse_quantity(self.call("eth_blockNumber", []), "block number")

    def logs(self, contract: str, topic: str, start: int, end: int) -> list[dict[str, Any]]:
        result = self.call("eth_getLogs", [{
            "address": contract,
            "topics": [topic],
            "fromBlock": hex(start),
            "toBlock": hex(end),
        }])
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise RpcError("eth_getLogs result must be an array of objects")
        return result


def _parse_quantity(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) < 3:
        raise RpcError(f"invalid {label} quantity")
    try:
        return int(value, 16)
    except ValueError as error:
        raise RpcError(f"invalid {label} quantity") from error
