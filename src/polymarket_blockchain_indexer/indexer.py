"""Bounded, resumable indexing of confirmed CTF OrderFilled logs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any

from .constants import CHAIN_ID, ORDER_FILLED_TOPIC
from .decoder import DecodeError, decode_order_filled
from .rpc import RpcError
from .storage import Store


class LogSource(Protocol):
    def chain_id(self) -> int: ...
    def latest_block(self) -> int: ...
    def logs(self, contract: str, topic: str, start: int, end: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class IndexResult:
    contract: str
    from_block: int
    through_block: int
    pages: int
    inserted: int


def index_contract(
    source: LogSource,
    store: Store,
    *,
    contract: str,
    initial_block: int,
    to_block: int,
    confirmations: int = 64,
    chunk_size: int = 1000,
) -> IndexResult:
    if initial_block < 0 or to_block < initial_block:
        raise ValueError("provide a non-negative, increasing block range")
    if confirmations < 0 or not 1 <= chunk_size <= 10000:
        raise ValueError("confirmations must be non-negative and chunk_size must be 1-10000")
    if source.chain_id() != CHAIN_ID:
        raise ValueError("RPC endpoint is not Polygon mainnet (chain ID 137)")
    safe_tip = source.latest_block() - confirmations
    if to_block > safe_tip:
        raise ValueError(
            f"requested block {to_block} exceeds confirmed tip {safe_tip}; "
            "lower --to-block or --confirmations"
        )

    current = store.next_block(contract, initial_block)
    resumed_from = current
    pages = inserted = 0
    span = chunk_size
    while current <= to_block:
        end = min(current + span - 1, to_block)
        try:
            logs = source.logs(contract, ORDER_FILLED_TOPIC, current, end)
        except RpcError as error:
            if error.range_too_large and span > 1:
                span = max(1, span // 2)
                continue
            raise
        try:
            fills = [decode_order_filled(log, contract) for log in logs]
        except DecodeError as error:
            raise DecodeError(f"blocks {current}-{end}: {error}") from error
        inserted += store.commit_range(contract, current, end, fills)
        pages += 1
        current = end + 1
    return IndexResult(contract, resumed_from, current - 1, pages, inserted)
