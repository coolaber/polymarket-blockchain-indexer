# Polymarket Blockchain Indexer

A read-only, resumable Python indexer for `OrderFilled` events emitted by Polymarket's **CTF Exchange V2** and **Neg Risk CTF Exchange** contracts on Polygon. It turns a bounded range of raw Polygon logs into a queryable SQLite database.

This repository demonstrates blockchain data engineering: ABI decoding, adaptive log queries, exact integer storage, and progress committed in the same transaction as the data. It does not place orders, use a wallet, calculate profit, or claim to cover every Polymarket protocol.

## Try it without a provider

Python 3.11 or newer is required. The runtime uses only the Python standard library.

```bash
python -m pip install -e .
polymarket-blockchain-indexer demo --db data/demo.sqlite
polymarket-blockchain-indexer status --db data/demo.sqlite
```

`demo` runs the real decoder and database pipeline against two **synthetic** RPC logs in blocks 101 and 103. It makes no network requests. The command prints the number of rows inserted; `status` shows the saved next block and row count. Running the demo twice inserts no duplicates.

To run from a clone without installation, set `PYTHONPATH=src` and use `python -m polymarket_blockchain_indexer` in place of the installed command. In PowerShell: `$env:PYTHONPATH = "src"`.

## Index a bounded live range

Use a Polygon JSON-RPC endpoint that supports historical `eth_getLogs` for the blocks you choose. Set its URL in the environment; the CLI never writes it to the database or prints it. [Polygon lists public and paid RPC providers](https://docs.polygon.technology/pos/reference/rpc-endpoints). The public endpoint below worked for the one-block check on 2026-10-14, but public providers may apply rate or history limits.

```bash
export POLYGON_RPC_URL="https://polygon.drpc.org"
polymarket-blockchain-indexer index \
  --from-block 94481672 --to-block 94481672 \
  --db data/ctf_fills.sqlite
polymarket-blockchain-indexer status --db data/ctf_fills.sqlite
```

PowerShell:

```powershell
$env:POLYGON_RPC_URL = "https://polygon.drpc.org"
polymarket-blockchain-indexer index --from-block 94481672 --to-block 94481672 --db data/ctf_fills.sqlite
polymarket-blockchain-indexer status --db data/ctf_fills.sqlite
```

On 2026-10-14, this one-block example returned 17 CTF fills and 12 Neg Risk CTF fills. Other providers may no longer retain that block or may impose different limits. The `.env.example` file is a template; the CLI does not load `.env` automatically. Set `POLYGON_RPC_URL` in the shell before running `index`.

The default `--contract both` scans the two documented CTF exchanges separately. You can select `--contract ctf` or `--contract neg-risk-ctf`. The first `--from-block` becomes that contract's saved starting block in the database. Reuse the same value when continuing that database, and raise `--to-block` to extend the scan.

The requested last block must be at least 64 blocks behind the provider's reported head by default. Set `--confirmations` explicitly if you need a different delay. `--chunk-size` starts at 1,000 blocks; if a provider rejects a range as too large, the indexer halves it and retries. HTTP 429, HTTP 5xx, and transport failures get bounded retries. A failed range leaves its checkpoint unchanged.

## What gets stored

`order_fills` stores the contract, block and transaction identity, indexed order hash, maker and taker addresses, maker side, token ID, amounts, fee, builder, and metadata. ABI `uint256` values are stored as decimal **text**, so SQLite cannot round or overflow them. Amounts remain raw contract units; the indexer does not infer token decimals, trade prices, market names, or P&L.

`scans` stores the initial block and next block for each contract. Every successful block range commits its decoded rows and new checkpoint in **one SQLite transaction**. A crash before that commit leaves the whole range available for the next run. The primary key `(contract, tx_hash, log_index)` protects event identity.

For example, after a run you can inspect the database with SQLite:

```sql
SELECT contract, COUNT(*) AS fills, MIN(block_number), MAX(block_number)
FROM order_fills
GROUP BY contract;
```

Generated databases and local environment files are excluded by `.gitignore`.

## Scope and limits

The supported addresses come from [Polymarket's Polygon contract list](https://docs.polymarket.com/resources/contracts), which also lists separate **Protocol V2** contracts. This project indexes only CTF Exchange V2 `OrderFilled` logs. It does not claim to be a complete Polymarket trade history. Its topic and fixed ABI layout were checked against the local CTF Exchange V2 ABI used by the source research project, then decoded successfully against real Polygon logs in the one-block check above.

The confirmation delay reduces exposure to ordinary chain reorganizations. The indexer does not automatically detect or repair a reorganization deeper than that delay. For a new scan or a different starting block, use a new database file. Provider history limits and rate limits vary. The demo and CI are offline; the one-block live check above does not guarantee that every provider or a long scan will work.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI runs the offline tests on Python 3.11, 3.12, and 3.13. The tests cover ABI validation, transport retries, provider range limits, interrupted scans, rollback of an incomplete range, confirmation checks, and the CLI demo.

```text
src/polymarket_blockchain_indexer/
  decoder.py   Validate and decode OrderFilled logs
  rpc.py       Read-only Polygon JSON-RPC client
  indexer.py   Confirmed, adaptive range processing
  storage.py   SQLite schema and atomic checkpoints
  demo.py      Synthetic offline data source
tests/         Offline behavior tests
```

This is an independent research and engineering project, not an official Polymarket tool.
