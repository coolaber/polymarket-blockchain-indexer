"""SQLite storage with range progress committed alongside decoded events."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from .decoder import OrderFill


class StorageError(RuntimeError):
    """A saved scan conflicts with the requested range."""


class Store:
    def __init__(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(destination)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                contract TEXT PRIMARY KEY,
                initial_block INTEGER NOT NULL,
                next_block INTEGER NOT NULL,
                CHECK (initial_block >= 0),
                CHECK (next_block >= initial_block)
            );
            CREATE TABLE IF NOT EXISTS order_fills (
                contract TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                order_hash TEXT NOT NULL,
                maker TEXT NOT NULL,
                taker TEXT NOT NULL,
                maker_side INTEGER NOT NULL,
                token_id TEXT NOT NULL,
                maker_amount TEXT NOT NULL,
                taker_amount TEXT NOT NULL,
                fee TEXT NOT NULL,
                builder TEXT NOT NULL,
                metadata TEXT NOT NULL,
                PRIMARY KEY (contract, tx_hash, log_index)
            );
            CREATE INDEX IF NOT EXISTS fills_block ON order_fills(contract, block_number);
        """)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def next_block(self, contract: str, initial_block: int) -> int:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO scans(contract, initial_block, next_block) VALUES (?, ?, ?)",
                (contract, initial_block, initial_block),
            )
        row = self.connection.execute(
            "SELECT initial_block, next_block FROM scans WHERE contract = ?", (contract,)
        ).fetchone()
        assert row is not None
        if row["initial_block"] != initial_block:
            raise StorageError(
                f"saved scan for {contract} starts at block {row['initial_block']}; "
                f"requested {initial_block}"
            )
        return int(row["next_block"])

    def commit_range(
        self, contract: str, start: int, end: int, fills: Sequence[OrderFill]
    ) -> int:
        """Insert a complete block range and advance its checkpoint in one transaction."""

        if end < start:
            raise ValueError("end must be at least start")
        if any(fill.contract != contract or not start <= fill.block_number <= end for fill in fills):
            raise StorageError("fill falls outside its contract or requested range")
        inserted = 0
        with self.connection:
            row = self.connection.execute(
                "SELECT next_block FROM scans WHERE contract = ?", (contract,)
            ).fetchone()
            if row is None or row["next_block"] != start:
                raise StorageError("range is not contiguous with the saved checkpoint")
            for fill in fills:
                cursor = self.connection.execute(
                    """INSERT INTO order_fills VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )""",
                    (
                        fill.contract, fill.block_number, fill.block_hash, fill.tx_hash,
                        fill.log_index, fill.order_hash, fill.maker, fill.taker,
                        fill.maker_side, fill.token_id, fill.maker_amount,
                        fill.taker_amount, fill.fee, fill.builder, fill.metadata,
                    ),
                )
                inserted += cursor.rowcount
            self.connection.execute(
                "UPDATE scans SET next_block = ? WHERE contract = ?", (end + 1, contract)
            )
        return inserted

    def status(self) -> list[dict[str, int | str]]:
        rows = self.connection.execute("""
            SELECT s.contract, s.initial_block, s.next_block,
                   COUNT(f.tx_hash) AS fills
            FROM scans AS s
            LEFT JOIN order_fills AS f ON f.contract = s.contract
            GROUP BY s.contract, s.initial_block, s.next_block
            ORDER BY s.contract
        """).fetchall()
        return [dict(row) for row in rows]
