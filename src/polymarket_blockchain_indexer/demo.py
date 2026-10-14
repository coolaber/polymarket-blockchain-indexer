"""Synthetic raw RPC logs for a fully offline demonstration."""

from __future__ import annotations

from typing import Any

from .constants import CHAIN_ID, ORDER_FILLED_TOPIC


def make_log(*, contract: str, block: int, tx_number: int, side: int) -> dict[str, Any]:
    """Build an illustrative OrderFilled log with ABI-sized fields."""

    word = lambda value: f"{value:064x}"
    maker = "11" * 20
    taker = "22" * 20
    return {
        "address": contract,
        "blockNumber": hex(block),
        "blockHash": "0x" + f"{block:064x}",
        "transactionHash": "0x" + f"{tx_number:064x}",
        "logIndex": "0x0",
        "removed": False,
        "topics": [
            ORDER_FILLED_TOPIC,
            "0x" + f"{tx_number + 1000:064x}",
            "0x" + "00" * 12 + maker,
            "0x" + "00" * 12 + taker,
        ],
        "data": "0x" + "".join((
            word(side), word(123456789), word(2_000_000), word(4_000_000),
            word(1000), word(0), word(0),
        )),
    }


class DemoSource:
    def __init__(self, contract: str) -> None:
        self.events = [
            make_log(contract=contract, block=101, tx_number=1, side=0),
            make_log(contract=contract, block=103, tx_number=2, side=1),
        ]

    def chain_id(self) -> int:
        return CHAIN_ID

    def latest_block(self) -> int:
        return 200

    def logs(self, contract: str, topic: str, start: int, end: int) -> list[dict[str, Any]]:
        return [
            event for event in self.events
            if event["address"] == contract
            and event["topics"][0] == topic
            and start <= int(event["blockNumber"], 16) <= end
        ]
