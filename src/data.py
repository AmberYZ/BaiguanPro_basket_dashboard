"""Price & fundamentals data layer.

Provider priority (try in order, first success wins):

  Prices — A-shares
    1. EODHD EOD (.SHG / .SHE)
    2. Tushare (if TUSHARE_TOKEN set)
    3. akshare Eastmoney
    4. akshare Sina

  Prices — HK
    1. EODHD EOD
    2. akshare HK daily

  Prices — benchmarks
    CSI300/CSI500: akshare CN index
    HSI: akshare Sina → Stooq
    SPX/NDX: akshare Sina → Stooq

  Fundamentals (PE/PB/Fwd PE/PEG/EV/EBITDA/…)
    1. EODHD fundamentals (preferred for Fwd PE / PEG / EV/EBITDA; also PE/PB when present)
    2. Fill gaps — A: Eastmoney spot → Baidu valuation; HK: Baidu valuation
    3. Price returns / RSI always from the local price cache

Everything is cached as parquet under data/. Run `python update_data.py`
(or the Update button in the app) to refresh.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

# DATA_DIR is env-configurable so a deployment can point the cache at a mounted
# persistent disk (e.g. Render). Falls back to the in-repo ./data for local dev.
DATA_DIR = Path(os.environ.get("DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
PRICES_DIR = DATA_DIR / "prices"
FUNDAMENTALS_PATH = DATA_DIR / "fundamentals.parquet"

START_DATE = "2023-01-01"


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the project .env without extra dependencies."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY", "")

BENCHMARKS = {
    "CSI300": {"label": "沪深300 CSI 300"},
    "CSI500": {"label": "中证500 CSI 500"},
    "HSI": {"label": "恒生指数 HSI"},
    "SPX": {"label": "S&P 500"},
    "NDX": {"label": "Nasdaq 100"},
}


def _ensure_dirs() -> None:
    PRICES_DIR.mkdir(parents=True, exist_ok=True)


def _normalize(df: pd.DataFrame, date_col: str, close_col: str) -> pd.Series:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    s = df.set_index(date_col)[close_col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[s.index >= START_DATE].rename("close")


def _eodhd_symbol(ticker: str) -> str:
    code, suffix = ticker.split(".")
    suffix = suffix.upper()
    if suffix == "SH":
        return f"{code}.SHG"
    if suffix == "SZ":
        return f"{code}.SHE"
    if suffix == "HK":
        return f"{code.lstrip('0') or '0'}.HK"
    return ticker


def _last_nested(data: dict, *paths):
    for path in paths:
        cur = data
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur not in (None, "", "None", "NA"):
            return cur
    return pd.NA


def _safe_float(value):
    try:
        if value in (None, "", "None", "NA") or pd.isna(value):
            return pd.NA
        return float(value)
    except Exception:  # noqa: BLE001
        return pd.NA


def _eps_growth_fwd(data: dict):
    """Consensus forward EPS growth (fraction) from EODHD.

    EODHD has no multi-year CAGR field. Best proxy for earnings expectations:
      1. Earnings.Trend entry with period '+1y' → earningsEstimateGrowth / growth
      2. Else EPSEstimateNextYear / EPSEstimateCurrentYear - 1 (when both > 0)
    Returns a fraction (e.g. 0.20 = +20%).
    """
    if not isinstance(data, dict):
        return pd.NA
    trend = (data.get("Earnings") or {}).get("Trend") or {}
    if isinstance(trend, dict) and trend:
        # Prefer the explicit +1y period; otherwise take furthest dated entry with growth.
        preferred = None
        dated = []
        for key, entry in trend.items():
            if not isinstance(entry, dict):
                continue
            growth = _safe_float(entry.get("earningsEstimateGrowth")
                                 if entry.get("earningsEstimateGrowth") not in (None, "", "None")
                                 else entry.get("growth"))
            if growth is pd.NA or pd.isna(growth):
                continue
            if entry.get("period") == "+1y":
                preferred = growth
                break
            dated.append((str(entry.get("date") or key), growth))
        if preferred is not None and preferred is not pd.NA and not pd.isna(preferred):
            return float(preferred)
        if dated:
            dated.sort()
            return float(dated[-1][1])

    highlights = data.get("Highlights") or {}
    cur = _safe_float(highlights.get("EPSEstimateCurrentYear"))
    nxt = _safe_float(highlights.get("EPSEstimateNextYear"))
    if (cur is not pd.NA and nxt is not pd.NA
            and not pd.isna(cur) and not pd.isna(nxt)
            and float(cur) > 0 and float(nxt) != 0):
        return float(nxt) / float(cur) - 1.0
    return pd.NA


def _rsi(series: pd.Series, window: int = 14) -> float | pd.NA:
    if series is None or len(series) < window + 2:
        return pd.NA
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    return _safe_float(out.iloc[-1])


# ---------------------------------------------------------------- A-shares

def _fetch_a_share_eodhd(ticker: str) -> pd.Series:
    url = f"https://eodhd.com/api/eod/{_eodhd_symbol(ticker)}"
    resp = requests.get(url, params={"api_token": EODHD_API_KEY, "fmt": "json",
                                     "from": START_DATE}, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if df.empty:
        raise RuntimeError(f"EODHD returned no A-share data for {ticker}")
    close_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
    return _normalize(df, "date", close_col)


def _fetch_a_share_tushare(ticker: str) -> pd.Series:
    import tushare as ts

    ts.set_token(TUSHARE_TOKEN)
    df = ts.pro_bar(ts_code=ticker, adj="qfq",
                    start_date=START_DATE.replace("-", ""))
    if df is None or df.empty:
        raise RuntimeError(f"tushare returned no data for {ticker}")
    return _normalize(df, "trade_date", "close")


def _fetch_a_share_akshare(ticker: str) -> pd.Series:
    import akshare as ak

    code = ticker.split(".")[0]
    df = ak.stock_zh_a_hist(symbol=code, period="daily",
                            start_date=START_DATE.replace("-", ""),
                            adjust="qfq")
    if df is None or df.empty:
        raise RuntimeError(f"akshare returned no data for {ticker}")
    return _normalize(df, "日期", "收盘")


def _fetch_a_share_sina(ticker: str) -> pd.Series:
    """Sina daily bars - more tolerant of proxies that drop eastmoney."""
    import akshare as ak

    code, suffix = ticker.split(".")
    df = ak.stock_zh_a_daily(symbol=f"{suffix.lower()}{code}", adjust="qfq")
    if df is None or df.empty:
        raise RuntimeError(f"sina returned no data for {ticker}")
    return _normalize(df, "date", "close")


# ---------------------------------------------------------------- HK

def _fetch_hk_eodhd(ticker: str) -> pd.Series:
    url = f"https://eodhd.com/api/eod/{_eodhd_symbol(ticker)}"
    resp = requests.get(url, params={"api_token": EODHD_API_KEY, "fmt": "json",
                                     "from": START_DATE}, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if df.empty:
        raise RuntimeError(f"EODHD returned no data for {ticker}")
    return _normalize(df, "date", "adjusted_close")


def _fetch_hk_akshare(ticker: str) -> pd.Series:
    import akshare as ak

    code = ticker.split(".")[0].zfill(5)
    df = ak.stock_hk_daily(symbol=code, adjust="qfq")
    if df is None or df.empty:
        raise RuntimeError(f"akshare returned no HK data for {ticker}")
    return _normalize(df, "date", "close")


# ---------------------------------------------------------------- Benchmarks

def _fetch_stooq(symbol: str) -> pd.Series:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if "Close" not in df.columns:
        raise RuntimeError(f"stooq returned no data for {symbol}")
    return _normalize(df, "Date", "Close")


def _fetch_cn_index(symbol: str) -> pd.Series:
    import akshare as ak

    df = ak.stock_zh_index_daily(symbol=symbol)
    return _normalize(df, "date", "close")


def _fetch_hsi_akshare() -> pd.Series:
    import akshare as ak

    df = ak.stock_hk_index_daily_sina(symbol="HSI")
    return _normalize(df, "date", "close")


def _fetch_us_index_sina(symbol: str) -> pd.Series:
    """US index history via sina (symbols like .INX, .NDX)."""
    import akshare as ak

    df = ak.index_us_stock_sina(symbol=symbol)
    return _normalize(df, "date", "close")


_BENCHMARK_FETCHERS = {
    "CSI300": [lambda: _fetch_cn_index("sh000300")],
    "CSI500": [lambda: _fetch_cn_index("sh000905")],
    "HSI": [_fetch_hsi_akshare, lambda: _fetch_stooq("^hsi")],
    "SPX": [lambda: _fetch_us_index_sina(".INX"), lambda: _fetch_stooq("^spx")],
    "NDX": [lambda: _fetch_us_index_sina(".NDX"), lambda: _fetch_stooq("^ndx")],
}


# ---------------------------------------------------------------- Public API

def fetch_price_series(ticker: str) -> pd.Series:
    """Fetch adjusted close series for a stock ticker, trying providers in order."""
    market = ticker.rsplit(".", 1)[-1].upper()
    if market in ("SH", "SZ", "BJ"):
        fetchers = []
        if EODHD_API_KEY:
            fetchers.append(_fetch_a_share_eodhd)
        if TUSHARE_TOKEN:
            fetchers.append(_fetch_a_share_tushare)
        fetchers.extend([_fetch_a_share_akshare, _fetch_a_share_sina])
    elif market == "HK":
        fetchers = []
        if EODHD_API_KEY:
            fetchers.append(_fetch_hk_eodhd)
        fetchers.append(_fetch_hk_akshare)
    else:
        raise ValueError(f"Unknown market suffix in {ticker}")

    errors = []
    for fetch in fetchers:
        try:
            return fetch(ticker)
        except Exception as exc:  # noqa: BLE001 - report all provider failures
            errors.append(f"{fetch.__name__}: {exc}")
    raise RuntimeError(f"All providers failed for {ticker}: {'; '.join(errors)}")


def fetch_benchmark_series(name: str) -> pd.Series:
    errors = []
    for fetch in _BENCHMARK_FETCHERS[name]:
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise RuntimeError(f"All providers failed for benchmark {name}: {'; '.join(errors)}")


def _price_path(key: str) -> Path:
    key = "" if key is None else str(key).strip()
    return PRICES_DIR / f"{key.replace('.', '_').replace('^', '')}.parquet"


def update_prices(tickers: list[str], benchmarks: list[str],
                  log=print) -> dict[str, str]:
    """Refresh the local cache. Returns {key: 'ok'|error message}."""
    _ensure_dirs()
    results = {}
    for t in tickers:
        try:
            s = fetch_price_series(t)
            s.to_frame().to_parquet(_price_path(t))
            results[t] = "ok"
            log(f"  {t}: {len(s)} rows through {s.index[-1].date()}")
        except Exception as exc:  # noqa: BLE001
            results[t] = str(exc)
            log(f"  {t}: FAILED - {exc}")
    for b in benchmarks:
        try:
            s = fetch_benchmark_series(b)
            s.to_frame().to_parquet(_price_path(b))
            results[b] = "ok"
            log(f"  {b}: {len(s)} rows through {s.index[-1].date()}")
        except Exception as exc:  # noqa: BLE001
            results[b] = str(exc)
            log(f"  {b}: FAILED - {exc}")
    return results


def load_price(key: str) -> pd.Series | None:
    if key is None:
        return None
    try:
        if pd.isna(key):
            return None
    except Exception:  # noqa: BLE001
        pass
    key = str(key).strip()
    if not key or key.lower() in {"nan", "none", "null"}:
        return None
    path = _price_path(key)
    if not path.exists():
        return None
    return pd.read_parquet(path)["close"]


def cache_age() -> str | None:
    """Human-readable age of the most recent cache write, or None if empty."""
    files = list(PRICES_DIR.glob("*.parquet")) if PRICES_DIR.exists() else []
    if not files:
        return None
    latest = max(f.stat().st_mtime for f in files)
    return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- Fundamentals

def _fundamentals_eastmoney(tickers: list[str]) -> pd.DataFrame:
    """Full A-share spot table from eastmoney (fast, one request)."""
    import akshare as ak

    codes = {t.split(".")[0] for t in tickers}
    df = ak.stock_zh_a_spot_em()
    df = df[df["代码"].isin(codes)]
    return pd.DataFrame({
        "code": df["代码"],
        "pe_ttm": df["市盈率-动态"],
        "pb": df["市净率"],
        "dv_ttm": pd.NA,
        "mkt_cap": df["总市值"],
        "source": "eastmoney",
    })


def _fundamentals_baidu(tickers: list[str], log=print) -> pd.DataFrame:
    """Per-stock valuation via Baidu Gushitong (supports both A-shares and HK)."""
    import akshare as ak

    rows = []
    for t in tickers:
        code = t.split(".")[0]
        is_hk = t.endswith(".HK")
        fetch = ak.stock_hk_valuation_baidu if is_hk else ak.stock_zh_valuation_baidu

        def latest(indicator):
            df = fetch(symbol=code, indicator=indicator, period="近一年")
            return float(df["value"].iloc[-1])

        try:
            row = {"code": code, "pe_ttm": latest("市盈率(TTM)"), "source": "baidu",
                   "pb": pd.NA, "dv_ttm": pd.NA, "mkt_cap": pd.NA}
            for indicator, col, scale in (("市净率", "pb", 1), ("总市值", "mkt_cap", 1e8)):
                try:
                    row[col] = latest(indicator) * scale
                except Exception:  # noqa: BLE001 - indicator not offered for HK
                    pass
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            log(f"  {t}: valuation fetch failed - {exc}")
    return pd.DataFrame(rows)


def _fundamentals_eodhd(tickers: list[str], log=print) -> pd.DataFrame:
    """EODHD fundamentals — preferred source for Fwd PE / PEG / EV/EBITDA and PE/PB when present."""
    if not EODHD_API_KEY:
        return pd.DataFrame()
    rows = []
    for ticker in tickers:
        symbol = _eodhd_symbol(ticker)
        url = f"https://eodhd.com/api/fundamentals/{symbol}"
        try:
            resp = requests.get(url, params={"api_token": EODHD_API_KEY, "fmt": "json"},
                                timeout=30)
            resp.raise_for_status()
            data = resp.json()
            general = data.get("General", {}) if isinstance(data, dict) else {}
            rows.append({
                "code": ticker.split(".")[0],
                "name_eodhd": general.get("Name") or general.get("EnglishName"),
                "pe_ttm": _safe_float(_last_nested(
                    data, ("Highlights", "PERatio"), ("Valuation", "TrailingPE"),
                    ("Highlights", "PERatioTTM"))),
                "pb": _safe_float(_last_nested(
                    data, ("Highlights", "PriceToBookMRQ"), ("Valuation", "PriceBookMRQ"),
                    ("Valuation", "PriceBookRatio"))),
                "dv_ttm": _safe_float(_last_nested(
                    data, ("Highlights", "DividendYield"), ("Valuation", "DividendYield"))),
                "mkt_cap": _safe_float(_last_nested(
                    data, ("Highlights", "MarketCapitalization"),
                    ("Highlights", "MarketCapMLN"))),
                "fwd_pe": _safe_float(_last_nested(
                    data, ("Highlights", "ForwardPE"), ("Valuation", "ForwardPE"),
                    ("Highlights", "ForwardAnnualPE"))),
                "peg": _safe_float(_last_nested(data, ("Highlights", "PEGRatio"))),
                "eps_growth": _eps_growth_fwd(data),
                "eps_growth_yoy": _safe_float(_last_nested(
                    data, ("Highlights", "QuarterlyEarningsGrowthYOY"))),
                "analyst_rating": _last_nested(
                    data, ("Highlights", "WallStreetRating"),
                    ("AnalystRatings", "Rating"), ("AnalystRatings", "RatingText")),
                "analyst_target": _safe_float(_last_nested(
                    data, ("Highlights", "WallStreetTargetPrice"),
                    ("AnalystRatings", "TargetPrice"))),
                "analyst_count": _safe_float(_last_nested(
                    data, ("AnalystRatings", "NumberAnalystOpinions"),
                    ("AnalystRatings", "StrongBuy"))),
                "ev_ebitda": _safe_float(_last_nested(
                    data, ("Valuation", "EnterpriseValueEbitda"),
                    ("Valuation", "EnterpriseValue/EBITDA"),
                    ("Highlights", "EVToEBITDA"))),
                "eodhd_source": symbol,
                "source": "eodhd",
            })
        except Exception as exc:  # noqa: BLE001
            log(f"  {ticker}: EODHD fundamentals unavailable - {exc}")
    return pd.DataFrame(rows)


def update_fundamentals(tickers: list[str], log=print) -> None:
    """Snapshot valuations for basket constituents.

    Cascade: EODHD first for every name, then fill PE/PB/mkt-cap gaps from
    Eastmoney (A) / Baidu (A+HK). Returns and RSI always come from price cache.
    """
    _ensure_dirs()
    a_tickers = [t for t in tickers if t.rsplit(".", 1)[-1] in ("SH", "SZ", "BJ")]
    hk_tickers = [t for t in tickers if t.endswith(".HK")]

    eodhd = _fundamentals_eodhd(tickers, log=log)
    eodhd = eodhd.set_index("code") if not eodhd.empty else pd.DataFrame()
    if not eodhd.empty:
        log(f"  EODHD fundamentals: {len(eodhd)} names")

    fill_frames = []
    code_to_a = {t.split(".")[0]: t for t in a_tickers}
    code_to_hk = {t.split(".")[0]: t for t in hk_tickers}

    def _needs_pe_fill(code: str) -> bool:
        if eodhd.empty or code not in eodhd.index:
            return True
        return pd.isna(eodhd.loc[code, "pe_ttm"]) if "pe_ttm" in eodhd.columns else True

    need_a = [code_to_a[c] for c in code_to_a if _needs_pe_fill(c)]
    need_hk = [code_to_hk[c] for c in code_to_hk if _needs_pe_fill(c)]

    if need_a:
        try:
            vals_a = _fundamentals_eastmoney(need_a)
            if vals_a.empty:
                raise RuntimeError("eastmoney spot returned no rows")
            log(f"  A-share valuation fill via eastmoney: {len(vals_a)} names")
            fill_frames.append(vals_a)
        except Exception as exc:  # noqa: BLE001
            log(f"  eastmoney spot unavailable ({exc}); falling back to baidu")
            vals_a = _fundamentals_baidu(need_a, log=log)
            log(f"  A-share valuation fill via baidu: {len(vals_a)} names")
            fill_frames.append(vals_a)

    if need_hk:
        vals_hk = _fundamentals_baidu(need_hk, log=log)
        log(f"  HK valuation fill via baidu: {len(vals_hk)} names")
        fill_frames.append(vals_hk)

    fill = (pd.concat([f for f in fill_frames if not f.empty], ignore_index=True)
            .set_index("code") if any(not f.empty for f in fill_frames) else pd.DataFrame())

    year_start = pd.Timestamp(datetime.now().year, 1, 1)
    rows = []
    for t in tickers:
        code = t.split(".")[0]
        s = load_price(t)
        row = {"code": code, "market": "HK" if t.endswith(".HK") else "A",
               "price": pd.NA, "pct_chg_1d": pd.NA, "pct_ytd": pd.NA,
               "pct_1m": pd.NA, "pct_3m": pd.NA, "pct_1y": pd.NA,
               "pe_ttm": pd.NA, "pb": pd.NA, "dv_ttm": pd.NA, "mkt_cap": pd.NA,
               "fwd_pe": pd.NA, "peg": pd.NA, "eps_growth": pd.NA,
               "eps_growth_yoy": pd.NA, "analyst_rating": pd.NA,
               "analyst_target": pd.NA, "analyst_count": pd.NA,
               "ev_ebitda": pd.NA, "rsi_14": pd.NA, "price_asof": pd.NA,
               "source": pd.NA, "eodhd_source": pd.NA, "name_eodhd": pd.NA}
        if s is not None and len(s) >= 2:
            row["price"] = s.iloc[-1]
            row["pct_chg_1d"] = (s.iloc[-1] / s.iloc[-2] - 1) * 100
            row["rsi_14"] = _rsi(s)
            row["price_asof"] = pd.Timestamp(s.index[-1]).date().isoformat()
            for days, col in ((30, "pct_1m"), (91, "pct_3m"), (365, "pct_1y")):
                past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
                if not past.empty:
                    row[col] = (s.iloc[-1] / past.iloc[-1] - 1) * 100
            prior = s[s.index < year_start]
            if not prior.empty:
                row["pct_ytd"] = (s.iloc[-1] / prior.iloc[-1] - 1) * 100
            else:
                in_year = s[s.index >= year_start]
                if not in_year.empty:
                    row["pct_ytd"] = (s.iloc[-1] / in_year.iloc[0] - 1) * 100

        # EODHD first
        if not eodhd.empty and code in eodhd.index:
            for col in ("name_eodhd", "pe_ttm", "pb", "dv_ttm", "mkt_cap",
                        "fwd_pe", "peg", "eps_growth", "eps_growth_yoy",
                        "analyst_rating", "analyst_target",
                        "analyst_count", "ev_ebitda", "eodhd_source", "source"):
                if col in eodhd.columns:
                    val = eodhd.loc[code, col]
                    if val is not None and not (isinstance(val, float) and pd.isna(val)):
                        row[col] = val
        # Fill gaps from Eastmoney / Baidu
        if not fill.empty and code in fill.index:
            for col in ("pe_ttm", "pb", "dv_ttm", "mkt_cap", "source"):
                if col in fill.columns and (row[col] is pd.NA or pd.isna(row[col])):
                    row[col] = fill.loc[code, col]
                    if col == "source" and pd.notna(fill.loc[code, col]):
                        row["source"] = fill.loc[code, col]
        rows.append(row)

    out = pd.DataFrame(rows)
    out["asof"] = datetime.now().isoformat(timespec="minutes")
    out.to_parquet(FUNDAMENTALS_PATH)


def load_fundamentals() -> pd.DataFrame | None:
    if not FUNDAMENTALS_PATH.exists():
        return None
    return pd.read_parquet(FUNDAMENTALS_PATH)


def fundamentals_for(tickers: list[str]) -> pd.DataFrame | None:
    df = load_fundamentals()
    if df is None:
        return None
    codes = {t.split(".")[0]: t for t in tickers}
    sub = df[df["code"].isin(codes)].copy()
    sub["ticker"] = sub["code"].map(codes)
    return sub.set_index("ticker")


def _symbol_list_path(exchange: str) -> Path:
    return DATA_DIR / f"symbol_list_{exchange.lower()}.parquet"


def _refresh_eodhd_symbol_list(exchange: str) -> pd.DataFrame:
    """Download and cache an EODHD exchange symbol list (HK / SHG / SHE)."""
    _ensure_dirs()
    resp = requests.get(
        f"https://eodhd.com/api/exchange-symbol-list/{exchange}",
        params={"api_token": EODHD_API_KEY, "fmt": "json"},
        timeout=45,
    )
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.to_parquet(_symbol_list_path(exchange))
    return df


def _load_eodhd_symbol_list(exchange: str, *, max_age_days: int = 7) -> pd.DataFrame:
    path = _symbol_list_path(exchange)
    if path.exists():
        age_days = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
        if age_days <= max_age_days:
            return pd.read_parquet(path)
    if not EODHD_API_KEY:
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()
    try:
        return _refresh_eodhd_symbol_list(exchange)
    except Exception:  # noqa: BLE001
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _normalize_cn_ticker(code: str, exchange: str) -> str | None:
    exchange = exchange.upper()
    raw = re.sub(r"\D", "", str(code))
    if not raw:
        return None
    if exchange == "HK":
        # Match basket convention: 09992.HK (5-digit zero-padded).
        return f"{raw.zfill(5)}.HK"
    suffix = {"SHG": "SH", "SHE": "SZ", "SHA": "SH", "SZA": "SZ",
              "SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(exchange)
    if not suffix:
        return None
    return f"{raw.zfill(6)}.{suffix}"


def _search_eodhd_symbol_lists(query: str, limit: int) -> list[dict]:
    """Search cached EODHD HK/A-share symbol directories (works when /search misses HK)."""
    q = query.strip().lower()
    q_digits = re.sub(r"\D", "", query)
    out: list[dict] = []
    for exchange in ("HK", "SHG", "SHE"):
        df = _load_eodhd_symbol_list(exchange)
        if df.empty:
            continue
        name_col = "Name" if "Name" in df.columns else None
        code_col = "Code" if "Code" in df.columns else None
        if not code_col:
            continue
        mask = df[code_col].astype(str).str.lower().str.contains(re.escape(q), na=False)
        if q_digits:
            mask = mask | df[code_col].astype(str).str.contains(q_digits, na=False)
        if name_col:
            mask = mask | df[name_col].astype(str).str.lower().str.contains(
                re.escape(q), na=False)
        hits = df[mask].head(limit)
        for _, row in hits.iterrows():
            ticker = _normalize_cn_ticker(row[code_col], exchange)
            if not ticker:
                continue
            out.append({
                "ticker": ticker,
                "name": (row[name_col] if name_col else None) or str(row[code_col]),
                "exchange": exchange,
                "type": row.get("Type", "Common Stock"),
                "source": f"eodhd-list:{exchange}",
            })
            if len(out) >= limit:
                return out
    return out


def _search_direct_code(query: str) -> list[dict]:
    """If the user typed a bare code, resolve it directly."""
    q = query.strip().upper().replace(" ", "")
    candidates: list[str] = []
    if re.fullmatch(r"\d{4,5}\.HK", q):
        code = q.split(".")[0]
        candidates.append(f"{code.zfill(5)}.HK")
    elif re.fullmatch(r"\d{4,5}", q):
        candidates.append(f"{q.zfill(5)}.HK")
        if len(q) == 6:
            for suf in ("SH", "SZ"):
                candidates.append(f"{q}.{suf}")
    elif re.fullmatch(r"\d{6}", q):
        if q.startswith(("5", "6", "9")):
            candidates.append(f"{q}.SH")
        elif q.startswith(("0", "3")):
            candidates.append(f"{q}.SZ")
        elif q.startswith(("4", "8")):
            candidates.append(f"{q}.BJ")
        else:
            candidates.extend([f"{q}.SH", f"{q}.SZ"])
    elif re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", q):
        candidates.append(q)

    out = []
    fund = load_fundamentals()
    for ticker in candidates:
        name = ticker
        if fund is not None and not fund.empty:
            code = ticker.split(".")[0]
            code_stripped = code.lstrip("0")
            rows = fund[
                fund["code"].astype(str).str.lstrip("0") == code_stripped
            ]
            if rows.empty:
                rows = fund[fund["code"].astype(str) == code]
            if not rows.empty and "name_eodhd" in rows.columns:
                name = rows.iloc[0].get("name_eodhd") or name
        out.append({
            "ticker": ticker,
            "name": name,
            "exchange": ticker.split(".")[-1],
            "type": "code",
            "source": "direct-code",
        })
    return out


def _search_eodhd_api(query: str, limit: int) -> list[dict]:
    if not EODHD_API_KEY:
        return []
    try:
        resp = requests.get(
            f"https://eodhd.com/api/search/{query}",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        out = []
        for item in resp.json()[:limit]:
            code = str(item.get("Code", "")).upper()
            exchange = str(item.get("Exchange", "")).upper()
            ticker = _normalize_cn_ticker(code, exchange)
            if not ticker and exchange in ("SHG", "SHE", "HK"):
                continue
            if not ticker:
                continue
            out.append({
                "ticker": ticker,
                "name": item.get("Name") or code,
                "exchange": exchange,
                "type": item.get("Type", ""),
                "source": "eodhd-search",
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def _search_cached_fundamentals(query: str, limit: int) -> list[dict]:
    df = load_fundamentals()
    if df is None or df.empty:
        return []
    pattern = re.escape(query.lower())
    name_series = df["name_eodhd"] if "name_eodhd" in df.columns else pd.Series("", index=df.index)
    candidates = df[
        df["code"].astype(str).str.lower().str.contains(pattern, na=False)
        | name_series.astype(str).str.lower().str.contains(pattern, na=False)
    ].head(limit)
    out = []
    for _, row in candidates.iterrows():
        if row.get("market") == "HK":
            ticker = f"{str(row['code']).zfill(5)}.HK"
            exchange = "HK"
        else:
            # Best-effort: keep code, default SH if unknown — price layer will validate.
            code = str(row["code"]).zfill(6)
            ticker = f"{code}.SH"
            exchange = "SH"
        out.append({
            "ticker": ticker,
            "name": row.get("name_eodhd") or row["code"],
            "exchange": exchange,
            "type": "cached",
            "source": "fundamentals-cache",
        })
    return out


def _search_basket_names(query: str, limit: int) -> list[dict]:
    """Match against names already used in basket YAML definitions."""
    try:
        from .baskets import load_baskets
    except Exception:  # noqa: BLE001
        return []
    q = query.lower()
    out = []
    seen = set()
    for b in load_baskets():
        for c in b.constituents:
            if c.ticker in seen:
                continue
            if q in c.ticker.lower() or q in (c.name or "").lower():
                seen.add(c.ticker)
                out.append({
                    "ticker": c.ticker,
                    "name": c.name,
                    "exchange": c.ticker.split(".")[-1],
                    "type": "basket",
                    "source": "basket-yaml",
                })
                if len(out) >= limit:
                    return out
    return out


def search_tickers(query: str, limit: int = 12) -> list[dict]:
    """Dynamic multi-source ticker search for A-shares and HK.

    Priority:
      1. Direct code (09992 / 09992.HK / 002594.SZ)
      2. EODHD exchange symbol lists (HK/SHG/SHE) — reliable for HK names
      3. EODHD free-text /search API (often weak for HK)
      4. Names already in basket YAML
      5. Cached fundamentals parquet
    """
    query = query.strip()
    if not query:
        return []

    merged: list[dict] = []
    seen: set[str] = set()

    def _absorb(items: list[dict]) -> None:
        for item in items:
            t = item["ticker"]
            if t in seen:
                continue
            seen.add(t)
            merged.append(item)
            if len(merged) >= limit:
                return

    _absorb(_search_direct_code(query))
    if len(merged) >= limit:
        return merged[:limit]
    # Chinese queries won't hit EODHD English names — check basket YAML early.
    if re.search(r"[\u4e00-\u9fff]", query):
        _absorb(_search_basket_names(query, limit))
        if len(merged) >= limit:
            return merged[:limit]
    _absorb(_search_eodhd_symbol_lists(query, limit))
    if len(merged) >= limit:
        return merged[:limit]
    _absorb(_search_eodhd_api(query, limit))
    if len(merged) >= limit:
        return merged[:limit]
    _absorb(_search_basket_names(query, limit))
    if len(merged) >= limit:
        return merged[:limit]
    _absorb(_search_cached_fundamentals(query, limit))
    return merged[:limit]


def quote_snapshot(ticker: str, *, prefer_live: bool = True) -> dict | None:
    """Latest close for confirming a search result.

    For search UI (prefer_live=True) hit EODHD first so brand-new tickers show
    the true latest close, not a month-old row. Falls back to the local cache.
    """
    live = _quote_from_eodhd(ticker) if (prefer_live and EODHD_API_KEY) else None
    if live is not None:
        return live
    cached = load_price(ticker)
    if cached is not None and not cached.empty:
        last = cached.iloc[-1]
        prev = cached.iloc[-2] if len(cached) > 1 else None
        return {
            "price": float(last),
            "asof": pd.Timestamp(cached.index[-1]).date().isoformat(),
            "chg_1d": float(last / prev - 1) if prev is not None else None,
            "source": "cache",
        }
    if not prefer_live and EODHD_API_KEY:
        return _quote_from_eodhd(ticker)
    return None


def _quote_from_eodhd(ticker: str) -> dict | None:
    try:
        symbol = _eodhd_symbol(ticker)
        # order=d → newest first. Must use rows[0], not rows[-1].
        from_date = (datetime.now().date() - pd.Timedelta(days=14)).isoformat()
        resp = requests.get(
            f"https://eodhd.com/api/eod/{symbol}",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "order": "d",
                    "from": from_date},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        last = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        close = _safe_float(last.get("adjusted_close")
                            if last.get("adjusted_close") not in (None, "")
                            else last.get("close"))
        if close is None or close is pd.NA:
            return None
        chg = None
        if prev is not None:
            prev_close = _safe_float(prev.get("adjusted_close")
                                     if prev.get("adjusted_close") not in (None, "")
                                     else prev.get("close"))
            if prev_close is not None and prev_close is not pd.NA and float(prev_close):
                chg = float(close) / float(prev_close) - 1
        return {
            "price": float(close),
            "asof": str(last.get("date", ""))[:10],
            "chg_1d": chg,
            "source": "eodhd",
        }
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- News

def _akshare_news_symbol(ticker: str) -> str:
    """Symbol for akshare ``stock_news_em`` (Eastmoney search)."""
    code, suffix = ticker.split(".")
    suffix = suffix.upper()
    if suffix == "HK":
        return code.lstrip("0") or "0"
    return code.zfill(6)


def fetch_news_eodhd(ticker: str, limit: int = 5) -> list[dict]:
    """Headlines for one ticker via EODHD (A-shares + HK when covered)."""
    if not EODHD_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://eodhd.com/api/news",
            params={
                "s": _eodhd_symbol(ticker),
                "limit": max(1, min(limit, 50)),
                "api_token": EODHD_API_KEY,
                "fmt": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        articles = []
        for item in payload:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            articles.append({
                "title": title,
                "date": str(item.get("date") or "")[:10],
                "link": str(item.get("link") or "").strip(),
                "source": "EODHD",
                "ticker": ticker,
            })
        return articles
    except Exception:  # noqa: BLE001
        return []


def fetch_news_akshare(ticker: str, limit: int = 5) -> list[dict]:
    """Eastmoney headlines via akshare (A-shares and HK)."""
    try:
        import akshare as ak

        symbol = _akshare_news_symbol(ticker)
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return []
        articles = []
        for _, row in df.head(limit).iterrows():
            title = row.get("新闻标题") or row.get("title")
            if title is None or (isinstance(title, float) and pd.isna(title)):
                continue
            title = str(title).strip()
            if not title:
                continue
            link = row.get("新闻链接") or row.get("link") or ""
            pub = row.get("发布时间") or row.get("public_time") or ""
            src = row.get("文章来源") or "东方财富"
            articles.append({
                "title": title,
                "date": str(pub)[:10],
                "link": str(link).strip() if link is not None else "",
                "source": str(src),
                "ticker": ticker,
            })
        return articles
    except Exception:  # noqa: BLE001
        return []


def fetch_ticker_news(ticker: str, limit: int = 5) -> list[dict]:
    """Per-ticker headlines from all available sources, de-duped, newest first."""
    merged: list[dict] = []
    seen: set[str] = set()
    for article in (
        *fetch_news_eodhd(ticker, limit),
        *fetch_news_akshare(ticker, limit),
    ):
        key = article.get("link") or article.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(article)
    merged.sort(key=lambda item: item.get("date") or "", reverse=True)
    return merged[:limit]


def merge_basket_news(
    tickers: list[str],
    *,
    limit_per_ticker: int = 5,
) -> list[dict]:
    """Merge and de-dupe headlines across basket constituents, newest first."""
    merged: list[dict] = []
    seen: set[str] = set()
    for ticker in tickers:
        for article in fetch_ticker_news(ticker, limit_per_ticker):
            key = article.get("link") or article.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(article)
    merged.sort(key=lambda item: item.get("date") or "", reverse=True)
    return merged
