"""Trailing PE history & basket valuation context.

EODHD does not publish historical Forward PE. We reconstruct monthly Trailing PE
from price ÷ TTM EPS (sum of last 4 quarterly epsActual), then compare today's
Forward PE against each name's / basket's own trail-PE distribution.

Fallback when EODHD earnings history is missing/thin: Baidu Gushitong
市盈率(TTM) daily series via akshare (A + HK), resampled to month-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

from .data import (DATA_DIR, EODHD_API_KEY, _eodhd_symbol, _ensure_dirs,
                   fundamentals_for, load_price)
from .ui import BLUE, GREEN, MUTED, ORANGE, RED, plotly_layout

PE_LOOKBACK_YEARS = 5
# Prefer EODHD-reconstructed series; fall back to Baidu if shorter than this.
MIN_PE_MONTHS = 6
EARNINGS_DIR = DATA_DIR / "earnings_history"
PE_HISTORY_PATH = DATA_DIR / "pe_history.parquet"


def _safe_pe(value) -> float | None:
    try:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return None
        if pd.isna(value):
            return None
        v = float(value)
        if v <= 0 or v > 200:
            return None
        return v
    except (TypeError, ValueError):
        return None


def fetch_earnings_history(ticker: str) -> dict:
    """Pull EODHD Earnings::History for one ticker (empty dict on failure)."""
    if not EODHD_API_KEY:
        return {}
    symbol = _eodhd_symbol(ticker)
    try:
        resp = requests.get(
            f"https://eodhd.com/api/fundamentals/{symbol}",
            params={"api_token": EODHD_API_KEY, "fmt": "json",
                    "filter": "Earnings::History"},
            timeout=30,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if isinstance(data, dict):
            if "History" in data and isinstance(data["History"], dict):
                return data["History"]
            earnings = data.get("Earnings")
            if isinstance(earnings, dict) and isinstance(earnings.get("History"), dict):
                return earnings["History"]
            # Filtered response may already be the history map keyed by date.
            sample = next(iter(data.values()), None)
            if isinstance(sample, dict) and "epsActual" in sample:
                return data
        return {}
    except Exception:  # noqa: BLE001
        return {}


def load_earnings_history(ticker: str) -> dict:
    path = EARNINGS_DIR / f"{ticker.replace('.', '_')}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_earnings_history(ticker: str, history: dict) -> None:
    _ensure_dirs()
    EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = EARNINGS_DIR / f"{ticker.replace('.', '_')}.json"
    path.write_text(json.dumps(history), encoding="utf-8")


def ttm_eps_series(earnings_history: dict) -> pd.Series:
    """TTM EPS = rolling sum of last 4 reported quarterly epsActual."""
    rows = []
    for date_str, row in (earnings_history or {}).items():
        if not isinstance(row, dict):
            continue
        eps = row.get("epsActual")
        if eps is None or eps in ("", "None", "NA"):
            continue
        try:
            eps = float(eps)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(eps):
            continue
        rows.append((pd.Timestamp(date_str), eps))
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({d: e for d, e in rows}).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    # Need 4 quarters; require at least 2 to avoid empty early history.
    ttm = s.rolling(4, min_periods=4).sum()
    return ttm.dropna()


def build_trailing_pe_history(price: pd.Series, earnings_history: dict) -> pd.Series:
    """Monthly trailing PE = month-end price / TTM EPS (forward-filled)."""
    ttm = ttm_eps_series(earnings_history)
    if ttm.empty or price is None or price.dropna().empty:
        return pd.Series(dtype=float)
    px = price.dropna().copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    eps = ttm.reindex(px.index, method="ffill")
    pe = px / eps
    pe = pe.replace([np.inf, -np.inf], np.nan)
    pe = pe[(pe > 0) & (pe < 250)]
    monthly = pe.resample("ME").last().dropna()
    return monthly


def fetch_pe_history_baidu(ticker: str) -> pd.Series:
    """Baidu Gushitong 市盈率(TTM) history via akshare — A-shares and HK only."""
    suffix = ticker.rsplit(".", 1)[-1].upper()
    code = ticker.split(".")[0]
    try:
        import akshare as ak
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)

    if suffix == "HK":
        fetch = ak.stock_hk_valuation_baidu
    elif suffix in ("SH", "SZ", "BJ"):
        fetch = ak.stock_zh_valuation_baidu
    else:
        return pd.Series(dtype=float)

    try:
        df = fetch(symbol=code, indicator="市盈率(TTM)", period="近五年")
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)
    if df is None or df.empty or "value" not in df.columns:
        return pd.Series(dtype=float)

    s = pd.Series(
        pd.to_numeric(df["value"], errors="coerce").values,
        index=pd.to_datetime(df["date"]),
    ).sort_index()
    s = s.replace([np.inf, -np.inf], np.nan)
    s = s[(s > 0) & (s < 250)].dropna()
    if s.empty:
        return s
    s.index = s.index.tz_localize(None)
    return s.resample("ME").last().dropna()


def resolve_pe_history(ticker: str, earnings_history: dict | None = None) -> tuple[pd.Series, str]:
    """Build monthly Trail PE: EODHD reconstruct first, Baidu TTM if missing/thin.

    Returns (series, source) where source is ``eodhd``, ``baidu``, or ``none``.
    """
    hist = earnings_history if earnings_history is not None else load_earnings_history(ticker)
    price = load_price(ticker)
    pe = build_trailing_pe_history(price, hist) if hist else pd.Series(dtype=float)
    if len(pe) >= MIN_PE_MONTHS:
        return pe, "eodhd"

    baidu = fetch_pe_history_baidu(ticker)
    if len(baidu) >= MIN_PE_MONTHS or (pe.empty and not baidu.empty):
        return baidu, "baidu"
    if not pe.empty:
        return pe, "eodhd"
    return pd.Series(dtype=float), "none"


def pe_stats_vs_history(
    pe_hist: pd.Series,
    current_trail: float | None,
    current_fwd: float | None,
    *,
    years: int = PE_LOOKBACK_YEARS,
) -> dict:
    empty = {
        "pe_5y_median": None,
        "pe_5y_mean": None,
        "pe_5y_p25": None,
        "pe_5y_p75": None,
        "pe_5y_min": None,
        "pe_5y_max": None,
        "trail_pctile_5y": None,
        "fwd_vs_5y_trail_pctile": None,
        "fwd_vs_5y_median_premium": None,
    }
    if pe_hist is None or pe_hist.empty:
        return empty
    cutoff = pe_hist.index.max() - pd.DateOffset(years=years)
    window = pe_hist[pe_hist.index >= cutoff]
    if window.empty:
        window = pe_hist

    def pctile(x, series):
        if x is None or series.empty:
            return None
        return float((series < x).mean() * 100)

    cur_t = current_trail if current_trail else float(window.iloc[-1])
    cur_f = current_fwd
    med = float(window.median())
    return {
        "pe_5y_median": med,
        "pe_5y_mean": float(window.mean()),
        "pe_5y_p25": float(window.quantile(0.25)),
        "pe_5y_p75": float(window.quantile(0.75)),
        "pe_5y_min": float(window.min()),
        "pe_5y_max": float(window.max()),
        "trail_pctile_5y": pctile(cur_t, window),
        "fwd_vs_5y_trail_pctile": pctile(cur_f, window),
        "fwd_vs_5y_median_premium": (cur_f / med - 1.0) if cur_f and med else None,
    }


def stock_pe_history(ticker: str) -> pd.Series:
    """Monthly trail PE for one ticker — prefer shared parquet cache."""
    frame = load_pe_history_frame()
    if frame is not None and ticker in frame.columns:
        s = frame[ticker].dropna()
        if not s.empty:
            return s
    pe, _source = resolve_pe_history(ticker)
    return pe


def basket_pe_history(tickers: list[str]) -> pd.Series:
    """Equal-weight average of available component monthly trail PE series."""
    cols = []
    for t in tickers:
        s = stock_pe_history(t)
        if s is not None and not s.empty:
            cols.append(s.rename(t))
    if not cols:
        return pd.Series(dtype=float)
    df = pd.concat(cols, axis=1).sort_index()
    return df.mean(axis=1, skipna=True).dropna()


def component_valuation_averages(tickers: list[str]) -> dict:
    """Average Forward PE / Trail PE / PEG across components with valid values."""
    fund = fundamentals_for(tickers)
    out = {
        "avg_fwd_pe": None,
        "avg_trail_pe": None,
        "avg_peg": None,
        "n_fwd": 0,
        "n_trail": 0,
    }
    if fund is None or fund.empty:
        return out
    fwd, trail, peg = [], [], []
    for t in tickers:
        if t not in fund.index:
            continue
        row = fund.loc[t]
        f = _safe_pe(row.get("fwd_pe"))
        p = _safe_pe(row.get("pe_ttm"))
        g = _safe_pe(row.get("peg"))
        if f is not None:
            fwd.append(f)
        if p is not None:
            trail.append(p)
        if g is not None:
            peg.append(g)
    out["avg_fwd_pe"] = float(np.mean(fwd)) if fwd else None
    out["avg_trail_pe"] = float(np.mean(trail)) if trail else None
    out["avg_peg"] = float(np.mean(peg)) if peg else None
    out["n_fwd"] = len(fwd)
    out["n_trail"] = len(trail)
    return out


def basket_valuation(tickers: list[str]) -> dict:
    """Basket-level valuation snapshot + 5y trail PE context."""
    avgs = component_valuation_averages(tickers)
    pe_h = basket_pe_history(tickers)
    cur_trail = float(pe_h.iloc[-1]) if not pe_h.empty else avgs["avg_trail_pe"]
    cur_fwd = avgs["avg_fwd_pe"]
    stats = pe_stats_vs_history(pe_h, cur_trail, cur_fwd)
    return {
        **avgs,
        **stats,
        "pe_hist": pe_h,
        "cur_trail_pe": cur_trail,
    }


def ytd_drawdown(index: pd.Series) -> float | None:
    """Drawdown from YTD peak to latest print."""
    if index is None or index.empty:
        return None
    end = index.index[-1]
    year_start = pd.Timestamp(end.year, 1, 1)
    ytd = index[index.index >= year_start].dropna()
    if ytd.empty:
        return None
    peak = float(ytd.max())
    last = float(ytd.iloc[-1])
    if peak <= 0:
        return None
    return last / peak - 1.0


def update_earnings_and_pe(tickers: list[str], log=print) -> None:
    """Fetch earnings history and rebuild the shared monthly PE history parquet.

    Cascade per ticker:
      1. EODHD Earnings::History → reconstruct Trail PE from price / TTM EPS
      2. If missing or < MIN_PE_MONTHS → Baidu 市盈率(TTM) via akshare (A/HK)
    """
    _ensure_dirs()
    EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    series_map: dict[str, pd.Series] = {}
    existing = load_pe_history_frame()
    if existing is not None:
        for col in existing.columns:
            s = existing[col].dropna()
            if not s.empty:
                series_map[col] = s

    for i, ticker in enumerate(tickers, 1):
        hist = fetch_earnings_history(ticker)
        if hist:
            save_earnings_history(ticker, hist)
            log(f"  earnings {ticker}: {len(hist)} quarters")
        else:
            hist = load_earnings_history(ticker)
            if hist:
                log(f"  earnings {ticker}: cached ({len(hist)} quarters)")
            else:
                log(f"  earnings {ticker}: unavailable")

        pe, source = resolve_pe_history(ticker, earnings_history=hist)
        if not pe.empty:
            series_map[ticker] = pe
            log(f"  pe {ticker}: {source} ({len(pe)} months)")
        else:
            log(f"  pe {ticker}: unavailable")
        if i % 10 == 0:
            log(f"  ...{i}/{len(tickers)}")

    if series_map:
        frame = pd.DataFrame(series_map).sort_index()
        frame.to_parquet(PE_HISTORY_PATH)
        log(f"  pe_history.parquet: {frame.shape[1]} names × {len(frame)} months")


def load_pe_history_frame() -> pd.DataFrame | None:
    if not PE_HISTORY_PATH.exists():
        return None
    try:
        return pd.read_parquet(PE_HISTORY_PATH)
    except Exception:  # noqa: BLE001
        return None


def richness_label(pctile: float | None) -> tuple[str, str]:
    """Return (short label, chip key) for a Fwd PE percentile vs own history."""
    if pctile is None or pd.isna(pctile):
        return ("—", "muted")
    if pctile < 40:
        return ("偏便宜", "cheap")
    if pctile <= 60:
        return ("中枢", "fair")
    return ("偏贵", "rich")


def basket_valuation_figure(
    basket_index: pd.Series,
    pe_hist: pd.Series,
    *,
    avg_fwd_pe: float | None,
    avg_trail_pe: float | None,
    stats: dict,
    height: int = 360,
) -> go.Figure:
    """Three-panel chart: YTD correction · Trail PE path · position in 5y range."""
    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=(
            "① 修正了多少（YTD峰值=100）",
            "② 估值轨迹（Trail PE）vs 今日 Fwd PE",
            "③ 今日估值落在5年什么位置",
        ),
        column_widths=[0.34, 0.38, 0.28],
        horizontal_spacing=0.08,
    )

    # Panel 1 — YTD path indexed to peak
    if basket_index is not None and not basket_index.empty:
        end = basket_index.index[-1]
        year_start = pd.Timestamp(end.year, 1, 1)
        ytd = basket_index[basket_index.index >= year_start].dropna()
        if not ytd.empty:
            peak_val = float(ytd.max())
            peak_idx = ytd.idxmax()
            indexed = ytd / peak_val * 100
            now = float(indexed.iloc[-1])
            fig.add_trace(
                go.Scatter(
                    x=indexed.index, y=indexed.values, mode="lines", name="Basket",
                    line=dict(color=BLUE, width=2.2), showlegend=False,
                    hovertemplate="%{x|%Y-%m-%d}<br>Index %{y:.1f}<extra></extra>",
                ),
                row=1, col=1,
            )
            fig.add_hline(y=100, line_dash="dot", line_color=MUTED, row=1, col=1)
            fig.add_hrect(
                y0=min(now, 100), y1=max(now, 100),
                fillcolor="rgba(255,92,119,0.10)", line_width=0, row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[peak_idx, indexed.index[-1]],
                    y=[100, now],
                    mode="markers+text",
                    text=["Peak", f"Now {now:.0f}"],
                    textposition=["top center", "bottom center"],
                    marker=dict(size=10, color=[ORANGE, RED]),
                    showlegend=False,
                    hovertemplate="%{text}<extra></extra>",
                ),
                row=1, col=1,
            )

    # Panel 2 — Trail PE path + current Fwd marker
    cutoff = None
    pe_win = pe_hist
    if pe_hist is not None and not pe_hist.empty:
        cutoff = pe_hist.index.max() - pd.DateOffset(years=PE_LOOKBACK_YEARS)
        pe_win = pe_hist[pe_hist.index >= cutoff]
        fig.add_trace(
            go.Scatter(
                x=pe_win.index, y=pe_win.values, mode="lines", name="Trail PE",
                line=dict(color="#7dd3fc", width=1.8), showlegend=False,
                hovertemplate="Trail PE %{y:.1f}<extra></extra>",
            ),
            row=1, col=2,
        )
        p25, p75, med = stats.get("pe_5y_p25"), stats.get("pe_5y_p75"), stats.get("pe_5y_median")
        if p25 is not None and p75 is not None:
            fig.add_hrect(
                y0=p25, y1=p75,
                fillcolor="rgba(245,158,11,0.14)", line_width=0, row=1, col=2,
            )
        if med is not None:
            fig.add_hline(y=med, line_dash="dot", line_color=ORANGE, row=1, col=2)
            fig.add_annotation(
                text="5y med", x=0, xref="x2 domain", y=med, yref="y2",
                showarrow=False, xanchor="left", yanchor="bottom",
                font=dict(size=10, color=ORANGE),
            )
        if avg_fwd_pe is not None and not pe_win.empty:
            fig.add_trace(
                go.Scatter(
                    x=[pe_win.index[-1]], y=[avg_fwd_pe],
                    mode="markers+text", text=[f"Fwd {avg_fwd_pe:.1f}"],
                    textposition="top right",
                    marker=dict(size=12, color=RED, symbol="diamond"),
                    showlegend=False,
                    hovertemplate="Current Fwd PE %{y:.1f}<extra></extra>",
                ),
                row=1, col=2,
            )

    # Panel 3 — range strip
    pe_min, pe_max = stats.get("pe_5y_min"), stats.get("pe_5y_max")
    p25, p75, med = stats.get("pe_5y_p25"), stats.get("pe_5y_p75"), stats.get("pe_5y_median")
    if pe_min is not None and pe_max is not None:
        fig.add_trace(
            go.Scatter(
                x=[pe_min, pe_max], y=["5y Trail PE", "5y Trail PE"],
                mode="lines", line=dict(color="#64748b", width=8),
                showlegend=False, hoverinfo="skip",
            ),
            row=1, col=3,
        )
        if p25 is not None and p75 is not None:
            fig.add_trace(
                go.Scatter(
                    x=[p25, p75], y=["5y Trail PE", "5y Trail PE"],
                    mode="lines", line=dict(color=ORANGE, width=14),
                    showlegend=False,
                    hovertemplate="IQR %{x:.1f}<extra></extra>",
                ),
                row=1, col=3,
            )
        xs, colors, symbols, texts = [], [], [], []
        if med is not None:
            xs.append(med); colors.append(ORANGE); symbols.append("diamond"); texts.append(f"Med {med:.1f}")
        trail_now = avg_trail_pe if avg_trail_pe is not None else (
            float(pe_win.iloc[-1]) if pe_win is not None and not pe_win.empty else None
        )
        if trail_now is not None:
            xs.append(trail_now); colors.append("#7dd3fc"); symbols.append("circle"); texts.append(f"Trail {trail_now:.1f}")
        if avg_fwd_pe is not None:
            xs.append(avg_fwd_pe); colors.append(RED); symbols.append("diamond"); texts.append(f"Fwd {avg_fwd_pe:.1f}")
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs, y=["5y Trail PE"] * len(xs),
                    mode="markers+text", text=texts, textposition="top center",
                    textfont=dict(size=10),
                    marker=dict(size=12, color=colors, symbol=symbols),
                    showlegend=False,
                    hovertemplate="%{text}<extra></extra>",
                ),
                row=1, col=3,
            )

    fig.update_yaxes(title_text="Index", row=1, col=1)
    fig.update_yaxes(title_text="P/E", row=1, col=2)
    fig.update_yaxes(showticklabels=False, row=1, col=3)
    fig.update_xaxes(title_text="P/E", row=1, col=3)
    fig.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=height)
    plotly_layout(fig, height=height)
    fig.update_layout(hovermode="closest", legend=dict(orientation="h", y=-0.2))
    return fig


# Drawdown scale for scatter: deep washout (neg) → near peak (0).
DD_SCALE = [
    [0.0, "#C0392B"],
    [0.5, "#E8C07D"],
    [1.0, "#0F6E6A"],
]


def fwd_pe_vs_ytd_scatter(rows: pd.DataFrame) -> go.Figure:
    """Fwd PE (x) vs YTD (y); color = drawdown from YTD peak.

    Read as: valuation level × year-to-date performance, with color showing
    whether price has washed out from the YTD high (red = deep DD, teal = near peak).
    Richness vs history lives in the valuation strip / basket detail — not here.
    """
    dd = rows["DD vs YTD peak"]
    labels = rows["Basket"].astype(str).map(_short_scatter_label)
    fig = go.Figure(
        go.Scatter(
            x=rows["avg_fwd_pe"],
            y=rows["YTD"] * 100,
            mode="markers+text",
            text=labels,
            textposition="top center",
            textfont=dict(size=10),
            cliponaxis=False,
            marker=dict(
                size=16,
                color=dd * 100,
                colorscale=DD_SCALE,
                colorbar=dict(
                    title=dict(text="DD vs<br>YTD peak %", side="right"),
                    thickness=14,
                    len=0.75,
                ),
                line=dict(width=1, color="rgba(28,36,48,0.25)"),
            ),
            customdata=np.stack([
                rows["avg_peg"].fillna(-1),
                rows["pe_5y_median"].fillna(-1),
                rows["fwd_vs_5y_median_premium"].fillna(0) * 100,
                rows["_id"],
                dd.fillna(0) * 100,
                rows["Basket"].astype(str),
            ], axis=-1),
            hovertemplate=(
                "<b>%{customdata[5]}</b>"
                "<br>Fwd PE %{x:.1f}<br>YTD %{y:.1f}%"
                "<br>DD vs YTD peak %{customdata[4]:.1f}%"
                "<br>PEG %{customdata[0]:.2f}<br>5y trail med %{customdata[1]:.1f}"
                "<br>Fwd vs 5y med %{customdata[2]:+.0f}%<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title="Fwd PE vs YTD return (color = DD vs YTD peak)",
        xaxis_title="Average Forward P/E",
        yaxis_title="YTD Return (%)",
        # Room for marker labels (top) and colorbar title (right).
        margin=dict(l=48, r=72, t=72, b=48),
    )
    plotly_layout(fig, height=520)
    # Keep the extra margins — plotly_layout resets them tighter.
    fig.update_layout(
        hovermode="closest",
        margin=dict(l=48, r=72, t=72, b=48),
    )
    return fig


def _short_scatter_label(name: str, max_len: int = 22) -> str:
    """Truncate long basket names so scatter labels stay on-canvas."""
    name = (name or "").strip()
    if len(name) <= max_len:
        return name
    return name[: max_len - 1].rstrip() + "…"

def return_drawdown_heatmap(rows: pd.DataFrame) -> go.Figure:
    """Homepage heatmap: 1M / 3M / YTD / DD vs YTD peak.

    ``rows`` should already be sorted top→bottom in the desired visual order
    (first row = top of chart).
    """
    cols = ["1M", "3M", "YTD", "DD vs YTD peak"]
    z = rows[cols].astype(float).mul(100).values
    text = np.vectorize(
        lambda v: f"{v:+.1f}%" if v == v else "—"
    )(z)
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=cols,
            y=rows["Basket"].tolist(),
            colorscale="RdYlGn",
            zmid=0,
            text=text,
            texttemplate="%{text}",
            colorbar=dict(title="%"),
            hovertemplate="<b>%{y}</b><br>%{x}: <b>%{text}</b><extra></extra>",
        )
    )
    fig.update_layout(
        title="Return / drawdown heatmap",
        margin=dict(l=20, r=20, t=50, b=20),
    )
    plotly_layout(fig, height=max(320, 80 + len(rows) * 36))
    # First row at TOP; closest hover so the cell under the cursor is exact.
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(hovermode="closest")
    return fig
