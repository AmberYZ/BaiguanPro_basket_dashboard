"""Shared helpers for the Streamlit pages."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics import (  # noqa: E402
    basket_index, basket_index_for_stats, excess_vs_benchmark, perf_stats,
)
from src.baskets import load_baskets  # noqa: E402
from src.data import BENCHMARKS, cache_age, load_fundamentals, load_price  # noqa: E402
from src.ui import admin_line  # noqa: E402

STATUS_BADGE = {"active": "Active", "proposed": "Proposed", "archived": "Archived"}
UNIVERSAL_BENCHMARKS = ["CSI300", "SPX", "NDX"]
HIDE_DRAFT_ON_CHARTS_KEY = "hide_draft_on_charts"


@st.cache_data(ttl=300)
def get_baskets():
    return load_baskets()


def hide_draft_on_charts() -> bool:
    """Global pref: omit proposed/archived baskets from Overview charts."""
    return bool(st.session_state.get(HIDE_DRAFT_ON_CHARTS_KEY, True))


def baskets_for_charts():
    """Baskets eligible for Overview / chart surfaces.

    When the global hide-draft setting is on, only ``active`` baskets are
    included. Basket Detail / Propose / Data Admin keep using ``get_baskets()``.
    """
    baskets = get_baskets()
    if hide_draft_on_charts():
        return [b for b in baskets if b.status == "active"]
    return list(baskets)


@st.cache_data(ttl=300)
def get_basket_index(basket_id: str):
    """Index from basket inception (formal tracking window)."""
    baskets = {b.id: b for b in load_baskets()}
    return basket_index(baskets[basket_id])


@st.cache_data(ttl=300)
def get_basket_index_stats(basket_id: str):
    """Longer lookback index so 1W/1M/3M/YTD work for newly created baskets."""
    baskets = {b.id: b for b in load_baskets()}
    return basket_index_for_stats(baskets[basket_id])


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


def basket_summary_rows(*, for_charts: bool = False) -> pd.DataFrame:
    """Performance summary rows for every (or chart-eligible) basket.

    Pass ``for_charts=True`` on Overview so the global hide-draft setting
    applies. Share / other callers keep the full list unless they filter.
    """
    baskets = baskets_for_charts() if for_charts else get_baskets()
    rows = []
    for b in baskets:
        idx = get_basket_index_stats(b.id)
        stats = (
            perf_stats(idx, inception=b.inception) if idx is not None else {}
        )
        excess = None
        if idx is not None:
            bench = get_price(UNIVERSAL_BENCHMARKS[0])
            if bench is not None:
                # Excess since formal inception, not the stats lookback start.
                since = idx[idx.index >= pd.Timestamp(b.inception)]
                if since is not None and len(since) >= 2:
                    excess = excess_vs_benchmark(since, bench)
        rows.append({
            "Basket": b.name,
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
            "Status": STATUS_BADGE.get(b.status, b.status),
            "Tags": ", ".join(b.tags),
            "Tickers": len(b.constituents),
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
