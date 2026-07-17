import streamlit as st

from app_pages._shared import UNIVERSAL_BENCHMARKS, cache_banner, get_baskets
from src.data import (EODHD_API_KEY, TUSHARE_TOKEN, update_fundamentals,
                      update_prices)
from src.ui import internal_badge, internal_page

internal_page()
st.title("Data & Update")
internal_badge("Data administration — internal only.")
baskets = get_baskets()
tickers = sorted({c.ticker for b in baskets for c in b.constituents})
benchmarks = sorted({bm for b in baskets for bm in b.benchmarks} | set(UNIVERSAL_BENCHMARKS))
cache_banner(tickers)

col1, col2, col3 = st.columns(3)
col1.metric("Stocks tracked", len(tickers))
col2.metric("Benchmarks", len(benchmarks))
col3.metric("Baskets", len(baskets))

st.markdown(
    f"- EODHD key: {'set (loaded from .env)' if EODHD_API_KEY else '**not set** — prices/fundamentals fall back to Tushare / akshare'}\n"
    f"- Tushare token: {'set (loaded from .env)' if TUSHARE_TOKEN else 'not set (skipped in A-share price cascade)'}"
)

with st.expander("Market data provider cascade", expanded=False):
    st.markdown(
        """
**Prices — A-shares** (`.SH` / `.SZ` / `.BJ`)
1. EODHD EOD → 2. Tushare → 3. akshare Eastmoney → 4. akshare Sina

**Prices — HK** (`.HK`)
1. EODHD EOD → 2. akshare HK daily

**Prices — benchmarks**
- CSI300 / CSI500: akshare CN index
- HSI / SPX / NDX: akshare Sina → Stooq

**Fundamentals** (PE, PB, Fwd PE, PEG, EPS Gr. (1Y), EV/EBITDA, mkt cap, …)
1. EODHD fundamentals (preferred for Fwd PE / PEG / EPS growth / EV/EBITDA; also PE/PB when present)
2. Fill PE/PB/mkt-cap gaps — A: Eastmoney spot → Baidu; HK: Baidu
3. Returns (1D / 1M / 3M / YTD) and RSI always from the local price cache

EPS Gr. (1Y) = consensus forward EPS growth (+1y from EODHD Earnings.Trend). EODHD has no multi-year CAGR field.
        """
    )

if st.button("Update all data now", type="primary"):
    log_area = st.container()
    logs = []

    def log(msg):
        logs.append(str(msg))

    with st.spinner("Fetching prices..."):
        results = update_prices(tickers, benchmarks, log=log)
    with st.spinner("Fetching fundamentals snapshot..."):
        try:
            update_fundamentals(tickers, log=log)
        except Exception as exc:  # noqa: BLE001
            log(f"fundamentals FAILED - {exc}")

    st.cache_data.clear()
    failed = {k: v for k, v in results.items() if v != "ok"}
    if failed:
        st.warning(f"{len(failed)} series failed: {', '.join(failed)}")
    else:
        st.success("All series updated.")
    with st.expander("Update log", expanded=bool(failed)):
        st.code("\n".join(logs))

st.caption("You can also run `.venv/bin/python update_data.py` from the terminal "
           "or a cron job / GitHub Action.")
