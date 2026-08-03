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
    Overview chart range, or a stats lookback) to build a comparable window
    against benchmarks / compute 1M·3M returns for young baskets.
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


# Enough calendar days so 5Y (260 weeks) period returns work for young baskets.
STATS_LOOKBACK_DAYS = 2000


def basket_index_for_stats(basket: Basket) -> pd.Series | None:
    """Lookback index for period returns — independent of basket inception.

    Uses weighted average of *available* constituents each day (a late-listed
    name does not truncate the whole series). Base = 100 at the first date
    where at least one constituent has a price in the lookback window.
    """
    weights = basket.weights
    prices: dict[str, pd.Series] = {}
    for ticker in weights:
        s = load_price(ticker)
        if s is not None and not s.empty:
            prices[ticker] = s
    if not prices:
        return None

    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=STATS_LOOKBACK_DAYS)
    df = pd.DataFrame(prices).sort_index()
    df = df[df.index >= start].ffill()
    if df.empty:
        return None

    # Rebase each name at its own first valid print in the window.
    base = df.apply(lambda c: c.dropna().iloc[0] if c.notna().any() else np.nan)
    rel = df.div(base)
    w = pd.Series({t: weights[t] for t in df.columns}, dtype=float)
    w = w / w.sum()

    weighted = rel.mul(w, axis=1)
    weight_avail = rel.notna().astype(float).mul(w, axis=1)
    denom = weight_avail.sum(axis=1).replace(0.0, np.nan)
    idx = (weighted.sum(axis=1, min_count=1) / denom) * 100.0
    idx = idx.dropna()
    if idx.empty:
        return None
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


# Google Finance chart windows (verified against google.com/finance):
# 1M = exactly 4 weeks. Longer tabs follow the same week grid used by
# GOOGLEFINANCE return4 / return13 / return52 / return156 / return260.
PERIOD_WEEKS: dict[str, int] = {
    "1W": 1,
    "1M": 4,
    "3M": 13,
    "6M": 26,
    "1Y": 52,
    "2Y": 104,
    "3Y": 156,
    "5Y": 260,
}

# Chart range controls — same cutoffs as PERIOD_WEEKS / YTD.
CHART_RANGES: dict[str, str | int] = {
    "3M": PERIOD_WEEKS["3M"],
    "6M": PERIOD_WEEKS["6M"],
    "YTD": "ytd",
    "1Y": PERIOD_WEEKS["1Y"],
    "2Y": PERIOD_WEEKS["2Y"],
    "3Y": PERIOD_WEEKS["3Y"],
    "5Y": PERIOD_WEEKS["5Y"],
}


def period_cutoff(end: pd.Timestamp, period: str) -> pd.Timestamp:
    """Start date for a Google-aligned window ending at ``end``."""
    if period == "YTD":
        return pd.Timestamp(end.year, 1, 1)
    weeks = PERIOD_WEEKS.get(period)
    if weeks is None:
        raise KeyError(f"Unknown period {period!r}")
    return end - pd.Timedelta(weeks=weeks)


def chart_range_start(end: pd.Timestamp, choice: str) -> pd.Timestamp:
    """Overview / detail chart window start (weeks or YTD)."""
    value = CHART_RANGES[choice]
    if value == "ytd":
        return pd.Timestamp(end.year, 1, 1)
    return end - pd.Timedelta(weeks=int(value))


def _series_period_return(
    series: pd.Series,
    *,
    period: str | None = None,
    weeks: int | None = None,
    days: int | None = None,
    ytd: bool = False,
) -> float | None:
    """Single-name return over a window ending at the last print.

    Prefer ``period`` keys (``1M`` / ``3M`` / ``YTD`` / …) — these follow
    Google Finance week lookbacks. ``ytd=True`` uses last close before Jan 1.
    """
    if series is None or len(series) < 2:
        return None
    last = float(series.iloc[-1])
    end = pd.Timestamp(series.index[-1])
    if period == "YTD" or ytd:
        year_start = pd.Timestamp(end.year, 1, 1)
        prior = series[series.index < year_start]
        if not prior.empty:
            return last / float(prior.iloc[-1]) - 1.0
        in_year = series[series.index >= year_start]
        if in_year.empty:
            return None
        return last / float(in_year.iloc[0]) - 1.0
    if period is not None:
        cutoff = period_cutoff(end, period)
    elif weeks is not None:
        cutoff = end - pd.Timedelta(weeks=weeks)
    elif days is not None:
        cutoff = end - pd.Timedelta(days=days)
    else:
        return None
    window = series[series.index <= cutoff]
    if window.empty:
        return None
    return last / float(window.iloc[-1]) - 1.0


_PERIOD_KEYS = ("1W", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "5Y")
_RET_KEY = {
    "1W": "ret_1w",
    "1M": "ret_1m",
    "3M": "ret_3m",
    "6M": "ret_6m",
    "YTD": "ret_ytd",
    "1Y": "ret_1y",
    "2Y": "ret_2y",
    "3Y": "ret_3y",
    "5Y": "ret_5y",
}


def series_period_returns(series: pd.Series) -> dict:
    """All Google-aligned period returns for one price series."""
    if series is None or series.empty:
        return {}
    out: dict = {"asof": series.index[-1]}
    for period in _PERIOD_KEYS:
        out[_RET_KEY[period]] = _series_period_return(series, period=period)
    return out


def ticker_period_returns(ticker: str) -> dict:
    """Live period returns for one ticker from the price cache."""
    s = load_price(ticker)
    if s is None or s.empty:
        return {}
    return series_period_returns(s)


def basket_period_returns(basket: Basket) -> dict:
    """Weighted-average constituent period returns (Google windows).

    Each name's own period return is computed from its price series, then
    combined with basket weights among names that have a valid print for that
    window — avoids reading returns off a long lookback index (past winners
    would dominate).
    """
    weights = basket.weights
    series_map: dict[str, pd.Series] = {}
    for ticker in weights:
        s = load_price(ticker)
        if s is not None and not s.empty:
            series_map[ticker] = s
    if not series_map:
        return {}

    asofs = [s.index[-1] for s in series_map.values()]
    out: dict = {"asof": max(asofs)}

    for period in _PERIOD_KEYS:
        num = 0.0
        den = 0.0
        for ticker, s in series_map.items():
            r = _series_period_return(s, period=period)
            if r is None or pd.isna(r):
                continue
            w = float(weights.get(ticker, 0.0))
            if w <= 0:
                continue
            num += w * float(r)
            den += w
        out[_RET_KEY[period]] = (num / den) if den > 0 else None
    return out


def perf_stats(
    index: pd.Series,
    *,
    inception: str | pd.Timestamp | None = None,
) -> dict:
    """Return-period and risk stats for a *single* index series (base 100).

    Prefer :func:`basket_perf_stats` for multi-name baskets — period returns
    read off a long lookback index overweight past winners.

    When ``inception`` is set, Since Inception / Sharpe / Max DD use the
    post-inception slice only. Period returns still use the full series.
    """
    if index is None or len(index) < 2:
        return {}
    periods = series_period_returns(index)
    last = index.iloc[-1]
    end = index.index[-1]

    if inception is not None:
        sub = index[index.index >= pd.Timestamp(inception)].dropna()
    else:
        sub = index
    if sub is None or len(sub) < 2:
        ret_inception = None
        vol = None
        sharpe = None
        drawdown = None
    else:
        ret_inception = float(sub.iloc[-1] / sub.iloc[0] - 1.0)
        daily = sub.pct_change().dropna()
        vol = daily.std() * np.sqrt(TRADING_DAYS) if len(daily) > 5 else None
        ann_return = daily.mean() * TRADING_DAYS if len(daily) > 5 else None
        sharpe = ann_return / vol if vol and vol > 0 and ann_return is not None else None
        drawdown = float((sub / sub.cummax() - 1.0).min())

    return {
        "last": last,
        "asof": end,
        **{k: periods.get(k) for k in _RET_KEY.values()},
        "ret_inception": ret_inception,
        "vol_ann": vol,
        "sharpe": sharpe,
        "max_dd": drawdown,
    }


def basket_perf_stats(basket: Basket) -> dict:
    """Basket stats: EW/weighted period returns + inception risk metrics.

    Period returns average each constituent's own Google-window return.
    Since Inception / Sharpe / Max DD use the formal inception buy-and-hold
    index when available, else the lookback index sliced at inception.
    """
    periods = basket_period_returns(basket)
    idx = basket_index(basket)
    if idx is None or len(idx) < 2:
        idx = basket_index_for_stats(basket)
        risk = (
            perf_stats(idx, inception=basket.inception)
            if idx is not None else {}
        )
    else:
        risk = perf_stats(idx, inception=basket.inception)

    return {
        "asof": periods.get("asof") or risk.get("asof"),
        **{k: periods.get(k) for k in _RET_KEY.values()},
        "ret_inception": risk.get("ret_inception"),
        "vol_ann": risk.get("vol_ann"),
        "sharpe": risk.get("sharpe"),
        "max_dd": risk.get("max_dd"),
        "last": risk.get("last"),
    }


def basket_index_ytd(basket: Basket) -> pd.Series | None:
    """Buy-and-hold path from last prior-year close (for YTD charts / drawdown)."""
    weights = basket.weights
    year = None
    prior_dates: list[pd.Timestamp] = []
    for ticker in weights:
        s = load_price(ticker)
        if s is None or s.empty:
            continue
        if year is None:
            year = int(s.index[-1].year)
        prior = s[s.index < pd.Timestamp(year, 1, 1)]
        if not prior.empty:
            prior_dates.append(prior.index[-1])
    if prior_dates:
        start = max(prior_dates)
    elif year is not None:
        start = pd.Timestamp(year, 1, 1)
    else:
        return None
    return basket_index(basket, start=start)


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
