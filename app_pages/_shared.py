"""Shared helpers for the Streamlit pages."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics import basket_index, excess_vs_benchmark, perf_stats  # noqa: E402
from src.baskets import load_baskets  # noqa: E402
from src.data import BENCHMARKS, cache_age, load_fundamentals, load_price  # noqa: E402
from src.ui import admin_line  # noqa: E402

STATUS_BADGE = {"active": "Active", "proposed": "Proposed", "archived": "Archived"}
UNIVERSAL_BENCHMARKS = ["CSI300", "SPX", "NDX"]


@st.cache_data(ttl=300)
def get_baskets():
    return load_baskets()


@st.cache_data(ttl=300)
def get_basket_index(basket_id: str):
    baskets = {b.id: b for b in load_baskets()}
    return basket_index(baskets[basket_id])


@st.cache_data(ttl=300)
def get_price(key: str):
    return load_price(key)


@st.cache_data(ttl=300)
def get_fundamentals():
    return load_fundamentals()


def market_asof(keys: list[str] | None = None) -> str:
    dates = []
    keys = keys or []
    for key in keys:
        s = get_price(key)
        if s is not None and not s.empty:
            dates.append(pd.Timestamp(s.index[-1]).date().isoformat())
    fund = get_fundamentals()
    if fund is not None and "asof" in fund.columns and len(fund):
        dates.append(str(fund["asof"].iloc[0])[:10])
    if not dates:
        return "Market data unavailable"
    return f"Market data as of {min(dates)}"


def basket_summary_rows() -> pd.DataFrame:
    rows = []
    for b in get_baskets():
        idx = get_basket_index(b.id)
        stats = perf_stats(idx) if idx is not None else {}
        excess = None
        if idx is not None:
            bench = get_price(UNIVERSAL_BENCHMARKS[0])
            if bench is not None:
                excess = excess_vs_benchmark(idx, bench)
        rows.append({
            "Basket": b.name,
            "Status": STATUS_BADGE.get(b.status, b.status),
            "Tags": ", ".join(b.tags),
            "Names": len(b.constituents),
            "1W": stats.get("ret_1w"),
            "1M": stats.get("ret_1m"),
            "3M": stats.get("ret_3m"),
            "YTD": stats.get("ret_ytd"),
            "1Y": stats.get("ret_1y"),
            "Since Inception": stats.get("ret_inception"),
            f"Excess vs CSI300": excess,
            "Max DD": stats.get("max_dd"),
            "Sharpe": stats.get("sharpe"),
            "Inception": b.inception,
            "_id": b.id,
            "_tags": list(b.tags),
        })
    return pd.DataFrame(rows)


def cache_banner(tickers: list[str] | None = None):
    """One small combined admin line: cache age + market as-of date."""
    age = cache_age()
    if age is None:
        st.warning("No price data cached yet — go to **Data & Update** and run an update first.")
        return
    asof = market_asof((tickers or []) + UNIVERSAL_BENCHMARKS)
    admin_line(f"{asof} · cache updated {age} · benchmarks {', '.join(UNIVERSAL_BENCHMARKS)}")
