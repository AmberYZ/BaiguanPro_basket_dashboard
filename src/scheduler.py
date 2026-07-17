"""In-process daily market-data refresh.

Hosts like Render can't share a persistent disk between a web service and a
separate cron job, so the scheduled update has to run *inside* the web service
— the one process that can read and write the mounted disk the dashboard serves
from. This module starts a single daemon thread that wakes once a day.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

_started = False
_lock = threading.Lock()


def _seconds_until(hour_utc: int, minute: int = 0) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_update() -> None:
    # Imported lazily to avoid import cycles and to pick up env-configured paths.
    from src.baskets import load_baskets
    from src.data import update_fundamentals, update_prices

    universal = {"CSI300", "SPX", "NDX"}
    baskets = load_baskets()
    tickers = sorted({c.ticker for b in baskets for c in b.constituents})
    benchmarks = sorted({bm for b in baskets for bm in b.benchmarks} | universal)
    print(f"[scheduler] daily update: {len(tickers)} stocks + {len(benchmarks)} benchmarks",
          flush=True)
    update_prices(tickers, benchmarks)
    try:
        update_fundamentals(tickers)
    except Exception as exc:  # noqa: BLE001
        print(f"[scheduler] fundamentals failed: {exc}", flush=True)
    print("[scheduler] daily update done", flush=True)


def _loop(hour_utc: int, minute: int) -> None:
    while True:
        time.sleep(_seconds_until(hour_utc, minute))
        try:
            _run_update()
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler] update error: {exc}", flush=True)
        # Step past the trigger minute so we don't recompute a ~0s wait and rerun.
        time.sleep(90)


def start_daily_update(hour_utc: int = 16, minute: int = 0) -> None:
    """Start a daemon thread that refreshes market data once per day.

    Default 16:00 UTC = 00:00 Asia/Shanghai (Beijing midnight). Safe to call
    repeatedly; only the first call actually starts the thread.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(
        target=_loop, args=(hour_utc, minute),
        daemon=True, name="daily-data-update",
    ).start()
