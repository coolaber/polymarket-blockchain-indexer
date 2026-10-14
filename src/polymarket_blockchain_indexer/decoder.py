"""Decode the fixed-size ABI fields of CTF Exchange V2 OrderFilled logs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .constants import ORDER_FILLED_TOPIC


class DecodeError(ValueError):
    """A log does not match the expected contract event schema."""


@dataclass(frozen=True)
class OrderFill:
    contract: str
    block_number: int
    block_hash: str
    tx_hash: str
    log_index: int
    order_hash: str
    maker: str
    taker: str
    maker_side: int
    token_id: str
    maker_amount: str
    taker_amount: str
    fee: str
    builder: str
    metadata: str


def _hex(value: Any, byte_count: int, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise DecodeError(f"{label} must be a hex string")
    digits = value[2:]
    if len(digits) != byte_count * 2:
        raise DecodeError(f"{label} must be {byte_count} bytes")
    try:
        int(digits, 16)
    except ValueError as error:
        raise DecodeError(f"{label} contains non-hex characters") from error
    return "0x" + digits.lower()


def _quantity(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) < 3:
        raise DecodeError(f"{label} must be a hex quantity")
    try:
        result = int(value, 16)
    except ValueError as error:
        raise DecodeError(f"{label} is not hex") from error
    if result < 0:
        raise DecodeError(f"{label} cannot be negative")
    return result


def decode_order_filled(log: Mapping[str, Any], expected_contract: str) -> OrderFill:
    """Validate identity, address, topics, and ABI data before storing a fill.

    Integer amounts remain exact decimal strings. Their asset units depend on
    the trade side and market, so this decoder does not infer prices or P&L.
    """

    contract = _hex(log.get("address"), 20, "contract")
    if contract != expected_contract.lower():
        raise DecodeError("log address does not match the requested contract")
    if log.get("removed") is True:
        raise DecodeError("RPC returned a removed log")
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 4:
        raise DecodeError("OrderFilled requires exactly four topics")
    topic0, order_hash, maker_topic, taker_topic = (
        _hex(value, 32, f"topic {index}") for index, value in enumerate(topics)
    )
    if topic0 != ORDER_FILLED_TOPIC:
        raise DecodeError("unexpected event signature")
    if int(maker_topic[2:26], 16) or int(taker_topic[2:26], 16):
        raise DecodeError("indexed address has nonzero padding")
    data = _hex(log.get("data"), 7 * 32, "event data")
    words = [data[2 + i * 64:2 + (i + 1) * 64] for i in range(7)]
    side = int(words[0], 16)
    if side not in (0, 1):
        raise DecodeError("maker side must be 0 or 1")

    return OrderFill(
        contract=contract,
        block_number=_quantity(log.get("blockNumber"), "blockNumber"),
        block_hash=_hex(log.get("blockHash"), 32, "blockHash"),
        tx_hash=_hex(log.get("transactionHash"), 32, "transactionHash"),
        log_index=_quantity(log.get("logIndex"), "logIndex"),
        order_hash=order_hash,
        maker="0x" + maker_topic[-40:],
        taker="0x" + taker_topic[-40:],
        maker_side=side,
        token_id=str(int(words[1], 16)),
        maker_amount=str(int(words[2], 16)),
        taker_amount=str(int(words[3], 16)),
        fee=str(int(words[4], 16)),
        builder="0x" + words[5],
        metadata="0x" + words[6],
    )
