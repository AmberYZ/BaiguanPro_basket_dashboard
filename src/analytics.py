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


# Yahoo Finance chart ranges (5d / 1mo / 3mo / 1y / 5y / ytd):
# calendar days / months / years via DateOffset — matches Yahoo tabs.
PERIOD_OFFSETS: dict[str, dict[str, int]] = {
    "5D": {"days": 5},
    "1M": {"months": 1},
    "3M": {"months": 3},
    "1Y": {"years": 1},
    "5Y": {"years": 5},
}

# Chart range controls — same cutoffs as PERIOD_OFFSETS / YTD.
CHART_RANGES: dict[str, str] = {
    "3M": "3M",
    "YTD": "YTD",
    "1Y": "1Y",
    "5Y": "5Y",
}


def period_cutoff(end: pd.Timestamp, period: str) -> pd.Timestamp:
    """Nominal start date for a Yahoo-aligned window ending at ``end``.

    Actual return base = last available close on or before this cutoff
    (see :func:`resolve_period_base`).
    """
    if period == "YTD":
        # YTD return uses last close *before* Jan 1; cutoff marks year start.
        return pd.Timestamp(end.year, 1, 1)
    spec = PERIOD_OFFSETS.get(period)
    if spec is None:
        raise KeyError(f"Unknown period {period!r}")
    if "days" in spec:
        return end - pd.Timedelta(days=spec["days"])
    return end - pd.DateOffset(**spec)


def resolve_period_base(
    series: pd.Series,
    period: str,
    *,
    end: pd.Timestamp | None = None,
) -> dict | None:
    """Resolve the exact base/end trading dates used for a period return.

    Returns ``{period, end, cutoff, base, rule}`` or ``None`` if unavailable.
    """
    if series is None or len(series) < 2:
        return None
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp(series.index[-1])
    # Align to last print on/before requested end (handles mixed calendars).
    up_to_end = series[series.index <= end_ts]
    if up_to_end.empty:
        return None
    end_ts = pd.Timestamp(up_to_end.index[-1])

    if period == "YTD":
        year_start = pd.Timestamp(end_ts.year, 1, 1)
        prior = series[series.index < year_start]
        if not prior.empty:
            base_ts = pd.Timestamp(prior.index[-1])
            rule = "last close before Jan 1"
        else:
            in_year = series[(series.index >= year_start) & (series.index <= end_ts)]
            if in_year.empty:
                return None
            base_ts = pd.Timestamp(in_year.index[0])
            rule = "first print in year (no prior-year close)"
        cutoff = year_start
    else:
        cutoff = period_cutoff(end_ts, period)
        window = series[series.index <= cutoff]
        if window.empty:
            return None
        base_ts = pd.Timestamp(window.index[-1])
        spec = PERIOD_OFFSETS[period]
        if "days" in spec:
            n = spec["days"]
            rule = f"{n} calendar day{'s' if n != 1 else ''} (Yahoo {n}d)"
        elif "months" in spec:
            n = spec["months"]
            rule = f"{n} calendar month{'s' if n != 1 else ''} (Yahoo {n}mo)"
        else:
            n = spec["years"]
            rule = f"{n} calendar year{'s' if n != 1 else ''} (Yahoo {n}y)"

    return {
        "period": period,
        "end": end_ts,
        "cutoff": pd.Timestamp(cutoff),
        "base": base_ts,
        "rule": rule,
    }


def period_windows(
    series: pd.Series,
    periods: list[str] | None = None,
    *,
    end: pd.Timestamp | None = None,
) -> list[dict]:
    """Resolved windows for the standard return columns."""
    periods = periods or ["5D", "1M", "3M", "YTD", "1Y"]
    rows = []
    for period in periods:
        row = resolve_period_base(series, period, end=end)
        if row is not None:
            rows.append(row)
    return rows


def format_period_windows_line(
    series: pd.Series | None,
    periods: list[str] | None = None,
    *,
    end: pd.Timestamp | None = None,
) -> str:
    """One-line caption: ``1M 07-03→07-31 · 3M …`` for UI double-checks."""
    if series is None or series.empty:
        return ""
    parts = []
    asof = None
    for row in period_windows(series, periods, end=end):
        asof = row["end"]
        parts.append(
            f"{row['period']} {row['base'].strftime('%Y-%m-%d')}→"
            f"{row['end'].strftime('%Y-%m-%d')}"
        )
    if not parts:
        return ""
    head = f"Return windows (as of {asof.strftime('%Y-%m-%d')}"
    head += "; base = last close on/before cutoff): "
    return head + " · ".join(parts)


def chart_range_start(
    end: pd.Timestamp,
    choice: str,
    reference: pd.Series | None = None,
) -> pd.Timestamp:
    """Chart rebase start — same base date as table / bar period returns.

    When ``reference`` is given, uses :func:`resolve_period_base` (YTD = last
    close *before* Jan 1; 1M/1Y = last close on/before the Yahoo cutoff).
    Without a reference, falls back to :func:`period_cutoff` (YTD = Jan 1),
    which makes the chart start at the first print *after* New Year and
    disagree with YTD table returns — pass a reference on Overview charts.
    """
    if choice not in CHART_RANGES:
        raise KeyError(f"Unknown chart range {choice!r}")
    if reference is not None and not reference.empty:
        row = resolve_period_base(reference, choice, end=end)
        if row is not None:
            return pd.Timestamp(row["base"])
    return period_cutoff(end, choice)


def rebase_for_period(
    series: pd.Series,
    choice: str,
    *,
    end: pd.Timestamp | None = None,
) -> pd.Series | None:
    """Rebase ``series`` to 100 at the same base used for period returns."""
    row = resolve_period_base(series, choice, end=end)
    if row is None:
        return None
    return rebase(series, row["base"])


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
    Yahoo Finance calendar months/years. ``ytd=True`` uses last close before Jan 1.
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


_PERIOD_KEYS = ("5D", "1M", "3M", "YTD", "1Y", "5Y")
_RET_KEY = {
    "5D": "ret_5d",
    "1M": "ret_1m",
    "3M": "ret_3m",
    "YTD": "ret_ytd",
    "1Y": "ret_1y",
    "5Y": "ret_5y",
}


def series_period_returns(series: pd.Series) -> dict:
    """All Yahoo-aligned period returns for one price series."""
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
    """Weighted-average constituent period returns (Yahoo calendar windows).

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

    Period returns average each constituent's own Yahoo-window return.
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
