"""Command-line interface for live indexing, offline demo, and status."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from .constants import CONTRACTS
from .decoder import DecodeError
from .demo import DemoSource
from .indexer import IndexResult, index_contract
from .rpc import PolygonRpc, RpcError
from .storage import StorageError, Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polymarket-blockchain-indexer",
        description="Index confirmed Polygon CTF OrderFilled logs into SQLite.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    live = commands.add_parser("index", help="index a bounded range from Polygon JSON-RPC")
    live.add_argument("--from-block", type=int, required=True, help="first block, inclusive")
    live.add_argument("--to-block", type=int, required=True, help="last block, inclusive")
    live.add_argument("--contract", choices=["both", *CONTRACTS], default="both")
    live.add_argument("--db", default="data/ctf_fills.sqlite")
    live.add_argument("--chunk-size", type=int, default=1000, help="initial RPC range size (1-10000)")
    live.add_argument("--confirmations", type=int, default=64, help="blocks held back from chain tip")
    live.add_argument("--timeout", type=float, default=30, help="seconds per RPC request")
    live.add_argument("--retries", type=int, default=4, help="transport retries per request")

    demo = commands.add_parser("demo", help="index two synthetic events without network access")
    demo.add_argument("--db", default="data/demo.sqlite")

    status = commands.add_parser("status", help="show saved ranges and event counts")
    status.add_argument("--db", default="data/ctf_fills.sqlite")
    return parser


def _print_result(result: IndexResult) -> None:
    if result.pages == 0:
        print(f"{result.contract}: already indexed through block {result.through_block}; 0 new fills")
        return
    print(
        f"{result.contract}: blocks {result.from_block}-{result.through_block}, "
        f"{result.pages} RPC range(s), {result.inserted} new fill(s)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            if not Path(args.db).is_file():
                raise ValueError(f"database does not exist: {args.db}")
            with Store(args.db) as store:
                for row in store.status():
                    print(
                        f"{row['contract']}: starts {row['initial_block']}, "
                        f"next {row['next_block']}, fills {row['fills']}"
                    )
            return 0

        if args.command == "demo":
            contract = CONTRACTS["ctf"]
            with Store(args.db) as store:
                result = index_contract(
                    DemoSource(contract), store, contract=contract,
                    initial_block=100, to_block=104, confirmations=0, chunk_size=2,
                )
                _print_result(result)
                print(f"Synthetic demo database: {args.db}")
            return 0

        rpc_url = os.environ.get("POLYGON_RPC_URL", "")
        if not rpc_url:
            raise ValueError("set POLYGON_RPC_URL to a Polygon JSON-RPC endpoint")
        rpc = PolygonRpc(rpc_url, timeout=args.timeout, retries=args.retries)
        selected = CONTRACTS.values() if args.contract == "both" else (CONTRACTS[args.contract],)
        with Store(args.db) as store:
            for contract in selected:
                result = index_contract(
                    rpc, store, contract=contract,
                    initial_block=args.from_block, to_block=args.to_block,
                    confirmations=args.confirmations, chunk_size=args.chunk_size,
                )
                _print_result(result)
        return 0
    except (ValueError, OSError, sqlite3.Error, RpcError, DecodeError, StorageError) as error:
        print(f"Indexer failed: {error}", file=sys.stderr)
        return 1
