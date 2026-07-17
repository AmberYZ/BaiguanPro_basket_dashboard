#!/usr/bin/env python
"""Refresh the local data cache: prices for all basket constituents,
benchmarks, and the fundamentals snapshot.

Usage: .venv/bin/python update_data.py
Optionally set TUSHARE_TOKEN / EODHD_API_KEY env vars to prefer those providers.
"""

from src.baskets import load_baskets
from src.data import update_fundamentals, update_prices

UNIVERSAL_BENCHMARKS = {"CSI300", "SPX", "NDX"}


def main() -> None:
    baskets = load_baskets()
    tickers = sorted({c.ticker for b in baskets for c in b.constituents})
    benchmarks = sorted({bm for b in baskets for bm in b.benchmarks} | UNIVERSAL_BENCHMARKS)

    print(f"Updating prices for {len(tickers)} stocks + {len(benchmarks)} benchmarks...")
    results = update_prices(tickers, benchmarks)

    print("Updating fundamentals snapshot...")
    try:
        update_fundamentals(tickers)
    except Exception as exc:  # noqa: BLE001
        print(f"  fundamentals FAILED - {exc}")

    failed = {k: v for k, v in results.items() if v != "ok"}
    print(f"\nDone. {len(results) - len(failed)}/{len(results)} series updated.")
    if failed:
        print("Failures:")
        for k, v in failed.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
