"""Clean, read-only views suitable for sharing."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_pages._shared import (UNIVERSAL_BENCHMARKS, basket_summary_rows,
                               get_basket_index, get_basket_index_stats,
                               get_baskets, get_price, market_asof)
from src.analytics import perf_stats, rebase
from src.data import fundamentals_for
from src.ui import (BLUE, market_table, metric_grid, performance_strip,
                    plotly_layout, tag_filter, valuation_strip)
from src.valuation import (basket_valuation, basket_valuation_figure,
                           richness_label, ytd_drawdown)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="stHeader"] { display: none !important; }
    .block-container { padding-top: 2rem; max-width: 1280px; }
    </style>
    """,
    unsafe_allow_html=True,
)

baskets = {b.id: b for b in get_baskets() if b.status == "active"}
view = st.query_params.get("share", "overview")

st.caption("BAIGUAN PRO INDEX")

if view == "basket":
    basket_id = st.query_params.get("basket", "")
    b = baskets.get(basket_id)
    if b is None:
        st.error("This basket is unavailable or not active.")
        st.stop()

    st.title(b.name)
    st.caption(f"Inception {b.inception} · {market_asof([c.ticker for c in b.constituents] + UNIVERSAL_BENCHMARKS)}")
    if b.tags:
        st.caption(" · ".join(b.tags))
    st.markdown(b.thesis)
    idx = get_basket_index(b.id)
    idx_stats = get_basket_index_stats(b.id)
    if idx_stats is not None:
        stats = perf_stats(idx_stats, inception=b.inception)
        metric_grid([
            ("1M", stats.get("ret_1m"), "pct"),
            ("3M", stats.get("ret_3m"), "pct"),
            ("YTD", stats.get("ret_ytd"), "pct"),
            ("1Y", stats.get("ret_1y"), "pct"),
            ("Since", stats.get("ret_inception"), "pct"),
            ("Sharpe", stats.get("sharpe"), "ratio"),
            ("Vol.", stats.get("vol_ann"), "pct"),
            ("Max DD", stats.get("max_dd"), "pct"),
        ])
        chart_idx = idx if idx is not None and not idx.empty else idx_stats
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=chart_idx.index, y=chart_idx.values, name=b.name,
                                 mode="lines", line=dict(color=BLUE, width=3)))
        for bm in UNIVERSAL_BENCHMARKS:
            s = get_price(bm)
            if s is not None:
                r = rebase(s, chart_idx.index[0])
                if r is not None:
                    fig.add_trace(go.Scatter(x=r.index, y=r.values, name=bm,
                                             mode="lines",
                                             line=dict(dash="dash", width=1.4)))
        plotly_layout(fig, 480)
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Essential data")
    tickers = [c.ticker for c in b.constituents]
    fund = fundamentals_for(tickers)
    rows = []
    for c in b.constituents:
        row = {"Ticker": c.ticker, "Name": c.name, "Price": None, "1M": None,
               "3M": None, "YTD": None, "Fwd PE": None, "PEG": None,
               "EPS Gr. (1Y)": None, "P/E": None, "P/B": None, "EV/EBITDA": None,
               "RSI (14)": None}
        if fund is not None and c.ticker in fund.index:
            f = fund.loc[c.ticker]
            row.update({
                "Price": f.get("price"),
                "1M": f.get("pct_1m") / 100 if pd.notna(f.get("pct_1m")) else None,
                "3M": f.get("pct_3m") / 100 if pd.notna(f.get("pct_3m")) else None,
                "YTD": f.get("pct_ytd") / 100 if pd.notna(f.get("pct_ytd")) else None,
                "Fwd PE": f.get("fwd_pe"), "PEG": f.get("peg"),
                "EPS Gr. (1Y)": f.get("eps_growth"),
                "P/E": f.get("pe_ttm"), "P/B": f.get("pb"),
                "EV/EBITDA": f.get("ev_ebitda"), "RSI (14)": f.get("rsi_14"),
            })
        rows.append(row)
    market_table(pd.DataFrame(rows), pct_cols=["1M", "3M", "YTD", "EPS Gr. (1Y)"],
                 formats={"Price": "{:.2f}", "Fwd PE": "{:.1f}", "PEG": "{:.2f}",
                          "P/E": "{:.1f}", "P/B": "{:.2f}", "EV/EBITDA": "{:.1f}",
                          "RSI (14)": "{:.1f}"})
    st.caption(market_asof(tickers))

    st.markdown("#### Valuation")
    val = basket_valuation(tickers)
    label, chip = richness_label(val.get("fwd_vs_5y_trail_pctile"))
    dd = ytd_drawdown(idx_stats) if idx_stats is not None else None
    valuation_strip(
        val.get("avg_fwd_pe"),
        val.get("pe_5y_mean"),
        val.get("avg_trail_pe") or val.get("cur_trail_pe"),
        conclusion=label,
        conclusion_key=chip,
        drawdown=dd,
    )
    pe_hist = val.get("pe_hist")
    chart_for_val = idx_stats if idx_stats is not None else idx
    if chart_for_val is not None and pe_hist is not None and not pe_hist.empty:
        st.plotly_chart(
            basket_valuation_figure(
                chart_for_val, pe_hist,
                avg_fwd_pe=val.get("avg_fwd_pe"),
                avg_trail_pe=val.get("avg_trail_pe") or val.get("cur_trail_pe"),
                stats=val,
            ),
            width="stretch",
        )
else:
    st.title("China investment themes")
    st.caption(market_asof(UNIVERSAL_BENCHMARKS))
    summary = basket_summary_rows()
    summary = summary[summary["_id"].isin(baskets)]

    all_tags = sorted({tag for tags in summary["_tags"] for tag in tags})
    selected_tags = tag_filter(all_tags, key="share_tag_filter")
    if selected_tags:
        mask = summary["_tags"].apply(
            lambda tags: any(t in tags for t in selected_tags))
        summary = summary[mask].reset_index(drop=True)
        if summary.empty:
            st.info("No baskets match the selected tags.")

    for row in range(0, len(summary), 2):
        cols = st.columns(2)
        for col, (_, item) in zip(cols, summary.iloc[row:row + 2].iterrows()):
            b = baskets[item["_id"]]
            with col:
                with st.container(border=True):
                    st.markdown(f"### [{b.name}](?share=basket&basket={b.id})")
                    if b.tags:
                        st.caption(" · ".join(b.tags))
                    performance_strip([
                        ("1M", item["1M"]), ("3M", item["3M"]),
                        ("YTD", item["YTD"]), ("1Y", item["1Y"]),
                    ])
                    idx = get_basket_index(b.id)
                    if idx is not None:
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=idx.index, y=idx.values,
                                                 name="Basket", mode="lines",
                                                 line=dict(color=BLUE, width=2.8)))
                        for bm in UNIVERSAL_BENCHMARKS:
                            s = get_price(bm)
                            if s is not None:
                                r = rebase(s, idx.index[0])
                                if r is not None:
                                    fig.add_trace(go.Scatter(
                                        x=r.index, y=r.values, name=bm, mode="lines",
                                        line=dict(dash="dot", width=1.2)))
                        plotly_layout(fig, 270)
                        st.plotly_chart(fig, width="stretch")

st.divider()
st.caption("Baiguan Pro · Research, not investment advice.")
