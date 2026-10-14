from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from urllib.error import HTTPError

from polymarket_blockchain_indexer.cli import main
from polymarket_blockchain_indexer.constants import CHAIN_ID, CONTRACTS, ORDER_FILLED_TOPIC
from polymarket_blockchain_indexer.decoder import DecodeError, decode_order_filled
from polymarket_blockchain_indexer.demo import DemoSource, make_log
from polymarket_blockchain_indexer.indexer import index_contract
from polymarket_blockchain_indexer.rpc import PolygonRpc, RpcError
from polymarket_blockchain_indexer.storage import StorageError, Store

CONTRACT = CONTRACTS["ctf"]


class FailingSource(DemoSource):
    def __init__(self, contract: str, fail_start: int | None = None) -> None:
        super().__init__(contract)
        self.fail_start = fail_start
        self.ranges: list[tuple[int, int]] = []

    def logs(self, contract: str, topic: str, start: int, end: int) -> list[dict]:
        self.ranges.append((start, end))
        if start == self.fail_start:
            raise RpcError("temporary provider failure")
        return super().logs(contract, topic, start, end)


class IndexerTests(unittest.TestCase):
    def test_decodes_fixed_abi_words_without_losing_uint256_precision(self) -> None:
        log = make_log(contract=CONTRACT, block=101, tx_number=7, side=1)
        fill = decode_order_filled(log, CONTRACT)
        self.assertEqual(fill.block_number, 101)
        self.assertEqual(fill.maker_side, 1)
        self.assertEqual(fill.token_id, "123456789")
        self.assertEqual(fill.maker, "0x" + "11" * 20)
        self.assertEqual(fill.taker_amount, "4000000")

    def test_rejects_wrong_topic_and_removed_log(self) -> None:
        log = make_log(contract=CONTRACT, block=101, tx_number=7, side=0)
        log["topics"][0] = "0x" + "00" * 32
        with self.assertRaisesRegex(DecodeError, "signature"):
            decode_order_filled(log, CONTRACT)
        log["topics"][0] = ORDER_FILLED_TOPIC
        log["removed"] = True
        with self.assertRaisesRegex(DecodeError, "removed"):
            decode_order_filled(log, CONTRACT)

    def test_restart_resumes_after_last_atomic_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fills.sqlite"
            first = FailingSource(CONTRACT, fail_start=102)
            with Store(database) as store:
                with self.assertRaises(RpcError):
                    index_contract(first, store, contract=CONTRACT, initial_block=100,
                                   to_block=104, confirmations=0, chunk_size=2)
                self.assertEqual(store.status()[0]["next_block"], 102)
                self.assertEqual(store.status()[0]["fills"], 1)

            resumed = FailingSource(CONTRACT)
            with Store(database) as store:
                result = index_contract(resumed, store, contract=CONTRACT,
                                        initial_block=100, to_block=104,
                                        confirmations=0, chunk_size=2)
                self.assertEqual(result.from_block, 102)
                self.assertEqual(store.status()[0]["next_block"], 105)
                self.assertEqual(store.status()[0]["fills"], 2)
            self.assertEqual(resumed.ranges[0][0], 102)

    def test_provider_range_limit_halves_chunk(self) -> None:
        class LimitedSource(DemoSource):
            def logs(self, contract: str, topic: str, start: int, end: int) -> list[dict]:
                if end > start:
                    raise RpcError("too many results", -32005)
                return super().logs(contract, topic, start, end)

        with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / "fills.sqlite") as store:
            result = index_contract(LimitedSource(CONTRACT), store, contract=CONTRACT,
                                    initial_block=100, to_block=104,
                                    confirmations=0, chunk_size=4)
            self.assertEqual(result.inserted, 2)
            self.assertEqual(result.pages, 5)

    def test_failed_insert_rolls_back_fills_and_checkpoint(self) -> None:
        fill = decode_order_filled(make_log(contract=CONTRACT, block=101, tx_number=1, side=0), CONTRACT)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / "fills.sqlite") as store:
            store.next_block(CONTRACT, 100)
            with self.assertRaises(sqlite3.IntegrityError):
                store.commit_range(CONTRACT, 100, 101, [fill, fill])
            self.assertEqual(store.status()[0]["next_block"], 100)
            self.assertEqual(store.status()[0]["fills"], 0)

    def test_wrong_chain_and_unconfirmed_tip_rejected(self) -> None:
        class WrongChain(DemoSource):
            def chain_id(self) -> int:
                return 1

        with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / "fills.sqlite") as store:
            with self.assertRaisesRegex(ValueError, "not Polygon"):
                index_contract(WrongChain(CONTRACT), store, contract=CONTRACT,
                               initial_block=100, to_block=104, confirmations=0)
            with self.assertRaisesRegex(ValueError, "confirmed tip"):
                index_contract(DemoSource(CONTRACT), store, contract=CONTRACT,
                               initial_block=100, to_block=199, confirmations=64)

    def test_offline_cli_demo_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "demo.sqlite")
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["demo", "--db", database]), 0)
                self.assertEqual(main(["status", "--db", database]), 0)
            self.assertIn("2 new fill(s)", output.getvalue())
            self.assertIn("fills 2", output.getvalue())


class RpcTests(unittest.TestCase):
    def test_json_rpc_request_and_result(self) -> None:
        requests: list[dict] = []

        def open_url(request: object, *, timeout: float) -> io.BytesIO:
            self.assertEqual(timeout, 3)
            requests.append(json.loads(request.data))  # type: ignore[attr-defined]
            return io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":"0x89"}')

        rpc = PolygonRpc("https://example.test/rpc", timeout=3, open_url=open_url)
        self.assertEqual(rpc.chain_id(), CHAIN_ID)
        self.assertEqual(requests[0]["method"], "eth_chainId")

    def test_http_rate_limit_retries(self) -> None:
        attempts = 0
        sleeps: list[float] = []

        def open_url(_request: object, *, timeout: float) -> io.BytesIO:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise HTTPError("https://example.test", 429, "rate limited", {}, None)
            return io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":"0x89"}')

        rpc = PolygonRpc("https://example.test", open_url=open_url, sleep=sleeps.append)
        self.assertEqual(rpc.chain_id(), CHAIN_ID)
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [0.5])


if __name__ == "__main__":
    unittest.main()
