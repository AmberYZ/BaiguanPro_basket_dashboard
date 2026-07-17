"""Basket index construction and performance statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .baskets import Basket
from .data import load_price

TRADING_DAYS = 252


def basket_index(
    basket: Basket,
    *,
    start: str | pd.Timestamp | None = None,
) -> pd.Series | None:
    """Weighted buy-and-hold index for a basket, base 100 at ``start``.

    Defaults to the basket inception date. Pass an earlier ``start`` (e.g. the
    Overview chart range) to build a comparable window against benchmarks.
    """
    weights = basket.weights
    prices = {}
    for ticker, w in weights.items():
        s = load_price(ticker)
        if s is not None and not s.empty:
            prices[ticker] = s
    if not prices:
        return None

    start_ts = pd.Timestamp(start) if start is not None else pd.Timestamp(basket.inception)
    df = pd.DataFrame(prices).sort_index()
    df = df[df.index >= start_ts]
    # Require at least one valid price per name at the base date; forward-fill gaps.
    df = df.ffill().dropna()
    if df.empty:
        return None

    rel = df / df.iloc[0]
    w = pd.Series({t: weights[t] for t in df.columns})
    w = w / w.sum()
    idx = (rel * w).sum(axis=1) * 100.0
    return idx.rename(basket.id)


def component_indices(basket: Basket) -> pd.DataFrame | None:
    """Constituent price series rebased to 100 at basket inception."""
    prices = {}
    for constituent in basket.constituents:
        s = load_price(constituent.ticker)
        if s is not None and not s.empty:
            prices[f"{constituent.name} ({constituent.ticker})"] = s
    if not prices:
        return None
    df = pd.DataFrame(prices).sort_index()
    df = df[df.index >= pd.Timestamp(basket.inception)].ffill().dropna(how="all")
    if df.empty:
        return None
    return df.div(df.iloc[0]).mul(100.0)


def rebase(series: pd.Series, start: pd.Timestamp) -> pd.Series | None:
    s = series[series.index >= start].dropna()
    if s.empty:
        return None
    return s / s.iloc[0] * 100.0


def perf_stats(index: pd.Series) -> dict:
    """Return-period and risk stats for an index series (base 100)."""
    if index is None or len(index) < 2:
        return {}
    last = index.iloc[-1]
    end = index.index[-1]

    def ret(days: int) -> float | None:
        cutoff = end - pd.Timedelta(days=days)
        window = index[index.index <= cutoff]
        if window.empty:
            return None
        return last / window.iloc[-1] - 1.0

    year_start = pd.Timestamp(end.year, 1, 1)
    # Prefer last close before year start (classic YTD); if the series begins
    # mid-year (e.g. basket inception in April), fall back to first print of the year.
    prior = index[index.index < year_start]
    if not prior.empty:
        ret_ytd = last / prior.iloc[-1] - 1.0
    else:
        in_year = index[index.index >= year_start]
        ret_ytd = (last / in_year.iloc[0] - 1.0) if not in_year.empty else None
    daily = index.pct_change().dropna()
    vol = daily.std() * np.sqrt(TRADING_DAYS) if len(daily) > 5 else None
    ann_return = daily.mean() * TRADING_DAYS if len(daily) > 5 else None
    sharpe = ann_return / vol if vol and vol > 0 and ann_return is not None else None
    drawdown = (index / index.cummax() - 1.0).min()

    return {
        "last": last,
        "asof": end,
        "ret_1w": ret(7),
        "ret_1m": ret(30),
        "ret_3m": ret(91),
        "ret_ytd": ret_ytd,
        "ret_1y": ret(365),
        "ret_inception": last / index.iloc[0] - 1.0,
        "vol_ann": vol,
        "sharpe": sharpe,
        "max_dd": drawdown,
    }


def excess_vs_benchmark(basket_idx: pd.Series, bench_idx: pd.Series) -> float | None:
    """Since-inception excess return vs a benchmark rebased to same start."""
    b = rebase(bench_idx, basket_idx.index[0])
    if b is None or b.empty:
        return None
    aligned = pd.concat([basket_idx, b], axis=1).ffill().dropna()
    if aligned.empty:
        return None
    bi, be = aligned.iloc[-1, 0], aligned.iloc[-1, 1]
    return (bi / aligned.iloc[0, 0]) - (be / aligned.iloc[0, 1])


def fmt_pct(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:+.1%}"
