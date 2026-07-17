import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_pages._shared import (basket_summary_rows, cache_banner,
                               get_basket_index, get_baskets, get_price,
                               UNIVERSAL_BENCHMARKS)
from src.analytics import basket_index, perf_stats, rebase
from src.baskets import load_baskets
from src.data import fundamentals_for
from src.ui import (BLUE, GREEN, RED, market_table, performance_strip,
                    plotly_layout, share_button, tag_filter)

RANGES = {"3M": 91, "6M": 183, "YTD": "ytd", "1Y": 365, "2Y": 730,
          "3Y": 1095, "5Y": 1825}


def range_start(end: pd.Timestamp, choice: str) -> pd.Timestamp:
    value = RANGES[choice]
    if value == "ytd":
        return pd.Timestamp(end.year, 1, 1)
    return end - pd.Timedelta(days=value)


def open_basket(basket_id: str) -> None:
    st.session_state["selected_basket_id"] = basket_id
    # Bump nonce so Plotly selection state is not restored when we return.
    st.session_state["chart_nav_nonce"] = st.session_state.get("chart_nav_nonce", 0) + 1
    st.query_params["basket"] = basket_id
    st.switch_page("app_pages/basket_detail.py")


def relative_performance_chart(frame: pd.DataFrame) -> go.Figure:
    """One row per basket/benchmark: YTD primary (sort key) with paired 3M bar.

    Baskets keep green/red YTD bars; benchmarks use blue (hatched) so they read
    as references in the same ranking. Click customdata is basket id for baskets
    and the benchmark key for benchmarks (ignored by maybe_open_from_chart).
    """
    ranked = frame[["Basket", "YTD", "3M", "_id"]].dropna(subset=["YTD"]).copy()
    ranked["_kind"] = "basket"

    bm_rows = []
    for bm in UNIVERSAL_BENCHMARKS:
        series = get_price(bm)
        if series is None or series.empty:
            continue
        stats = perf_stats(series)
        ytd = stats.get("ret_ytd")
        if ytd is None:
            continue
        bm_rows.append({
            "Basket": bm,
            "YTD": ytd,
            "3M": stats.get("ret_3m"),
            "_id": bm,
            "_kind": "benchmark",
        })
    if bm_rows:
        ranked = pd.concat([ranked, pd.DataFrame(bm_rows)], ignore_index=True)

    ranked = ranked.sort_values("YTD")
    ytd_colors = [
        (BLUE if v >= 0 else "rgba(94,160,255,0.55)")
        if kind == "benchmark"
        else (GREEN if v >= 0 else RED)
        for kind, v in zip(ranked["_kind"], ranked["YTD"])
    ]
    m3_colors = [
        "rgba(94,160,255,0.28)" if kind == "benchmark" else "rgba(148,163,184,0.45)"
        for kind in ranked["_kind"]
    ]
    patterns = ["/" if kind == "benchmark" else "" for kind in ranked["_kind"]]
    hover_kind = [
        "Benchmark" if kind == "benchmark" else "Basket"
        for kind in ranked["_kind"]
    ]
    # [id, kind-label] so clicks still resolve to id; hover shows basket vs benchmark.
    custom = list(zip(ranked["_id"], hover_kind))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=ranked["Basket"],
        x=ranked["YTD"],
        name="YTD",
        orientation="h",
        customdata=custom,
        marker=dict(color=ytd_colors, pattern_shape=patterns),
        text=[f"{v:+.1%}" for v in ranked["YTD"]],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{customdata[1]} %{y}<br>YTD %{x:+.1%}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=ranked["Basket"],
        x=ranked["3M"],
        name="3M",
        orientation="h",
        customdata=custom,
        marker=dict(color=m3_colors, pattern_shape=patterns),
        text=[f"{v:+.1%}" if pd.notna(v) else "—" for v in ranked["3M"]],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{customdata[1]} %{y}<br>3M %{x:+.1%}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(229,231,235,0.45)", line_width=1)
    fig.update_xaxes(tickformat="+.0%", title=None, automargin=True)
    fig.update_yaxes(title=None, automargin=True)
    fig.update_layout(
        title="Relative performance — sorted by YTD (click a basket to open)",
        barmode="group",
        bargap=0.28,
        bargroupgap=0.12,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=20, r=60, t=60, b=20),
        showlegend=True,
    )
    plotly_layout(fig, height=max(340, 90 + len(ranked) * 58))
    return fig


def maybe_open_from_chart(event, *, fallback_id: str | None = None) -> None:
    """Open Basket Detail when the user selects a point/bar on a Plotly chart."""
    if event is None:
        return
    selection = getattr(event, "selection", None)
    if not selection:
        return
    points = getattr(selection, "points", None) or []
    if not points:
        return
    point = points[0]
    if not isinstance(point, dict):
        try:
            point = dict(point)
        except Exception:  # noqa: BLE001
            point = {}
    basket_id = None
    custom = point.get("customdata")
    if custom is not None:
        basket_id = custom[0] if isinstance(custom, (list, tuple)) else custom
    if not basket_id:
        basket_id = fallback_id
    if basket_id and basket_id not in UNIVERSAL_BENCHMARKS:
        open_basket(str(basket_id))


nav_nonce = st.session_state.get("chart_nav_nonce", 0)

title_col, btn_col = st.columns([4, 1])
with title_col:
    st.title("Baiguan Pro Index — Basket Overview")
with btn_col:
    share_button("Share view", "?share=overview")
cache_banner()

df = basket_summary_rows()
if df.empty:
    st.info("No baskets yet. Add YAML files under `baskets/` or use **Propose a Basket**.")
    st.stop()

all_tags = sorted({tag for tags in df["_tags"] for tag in tags})
selected_tags = tag_filter(all_tags)
if selected_tags:
    mask = df["_tags"].apply(lambda tags: any(t in tags for t in selected_tags))
    df = df[mask].reset_index(drop=True)
    if df.empty:
        st.info("No baskets match the selected tags.")
        st.stop()

baskets = [b for b in get_baskets() if b.id in set(df["_id"])]
basket_links = {
    row["Basket"]: f"/basket_detail?basket={row['_id']}"
    for _, row in df.iterrows()
}

pct_cols = ["1W", "1M", "3M", "YTD", "1Y", "Since Inception", "Excess vs CSI300", "Max DD"]
st.caption("Click a basket name to open its detail page.")
market_table(
    df.drop(columns=["_id", "_tags"]),
    pct_cols=pct_cols,
    formats={"Sharpe": "{:.2f}", "Names": "{:.0f}"},
    link_map={"Basket": basket_links},
    col_help={
        "Excess vs CSI300": "Since inception: basket return minus CSI300 return, both rebased at the basket's inception date.",
        "Max DD": "Maximum drawdown since inception (largest peak-to-trough decline).",
        "Sharpe": "Since inception: annualized daily return / annualized volatility (no risk-free rate).",
        "Since Inception": "Total return from the basket's inception date.",
        "1Y": "Trailing 12-month return; blank when the basket is younger than one year.",
    },
)

st.subheader("Performance")
range_choice = st.segmented_control(
    "Time range", list(RANGES), default="1Y", selection_mode="single",
) or "1Y"

fig = go.Figure()
basket_objs = {b.id: b for b in load_baskets()}
ends = []
for b in baskets:
    idx0 = get_basket_index(b.id)
    if idx0 is not None and not idx0.empty:
        ends.append(idx0.index[-1])
for bm in UNIVERSAL_BENCHMARKS:
    bench = get_price(bm)
    if bench is not None and not bench.empty:
        ends.append(bench.index[-1])

if not ends:
    st.info("No price series available for the current filter.")
else:
    latest = pd.Timestamp(max(ends))
    start = range_start(latest, range_choice)

    for b in baskets:
        obj = basket_objs.get(b.id)
        if obj is None:
            continue
        # Rebuild from the selected start so the line opens at 100 with benchmarks.
        idx = basket_index(obj, start=start)
        if idx is None or idx.empty:
            continue
        fig.add_trace(go.Scatter(
            x=idx.index,
            y=idx.values,
            name=b.name,
            customdata=[b.id] * len(idx),
            mode="lines",
            line=dict(width=2.5),
        ))
    for bm in UNIVERSAL_BENCHMARKS:
        bench = get_price(bm)
        if bench is None or bench.empty:
            continue
        r = rebase(bench, start)
        if r is None or r.empty:
            continue
        fig.add_trace(go.Scatter(
            x=r.index,
            y=r.values,
            name=bm,
            mode="lines",
            line=dict(width=1.5, dash="dash"),
        ))

    fig.update_xaxes(range=[start, latest])
    fig.update_yaxes(title="Rebased to 100 at range start")
    plotly_layout(fig, height=460)
    event = st.plotly_chart(
        fig, width="stretch", key=f"overview_perf_{nav_nonce}",
        on_select="rerun", selection_mode="points",
    )
    maybe_open_from_chart(event)
    st.caption(
        f"All series are rebased to 100 at the start of {range_choice} "
        f"({start.date()}). Click a basket line to open its detail page."
    )

st.subheader("Relative performance")
st.caption("Baskets and benchmarks (CSI300 / SPX / NDX) sorted by YTD. Grey basket / blue hatched benchmark bars; 3M is the paired secondary. Click a basket to open detail.")
event_rel = st.plotly_chart(
    relative_performance_chart(df), width="stretch",
    key=f"rank_rel_{nav_nonce}", on_select="rerun", selection_mode="points",
)
maybe_open_from_chart(event_rel)

st.subheader("Many charts")
many_range = st.segmented_control(
    "Card range", ["3M", "YTD"], default="YTD", selection_mode="single",
) or "YTD"
st.caption("Click a basket title or its chart to open Basket Detail.")

for row in range(0, len(baskets), 2):
    cols = st.columns(2)
    for col, b in zip(cols, baskets[row:row + 2]):
        with col:
            with st.container(border=True):
                idx = get_basket_index(b.id)
                stats_row = df[df["_id"] == b.id].iloc[0]
                title_col, open_col = st.columns([5, 1])
                with title_col:
                    st.markdown(
                        f"#### [{b.name}](/basket_detail?basket={b.id})"
                    )
                with open_col:
                    if st.button("Open", key=f"open_{b.id}", width="stretch"):
                        open_basket(b.id)
                if b.tags:
                    st.caption(" · ".join(b.tags))
                performance_strip(
                    [("1M", stats_row["1M"]), ("3M", stats_row["3M"]),
                     ("YTD", stats_row["YTD"]), ("1Y", stats_row["1Y"])]
                )
                mini = go.Figure()
                mini_end = latest if ends else pd.Timestamp.today()
                mini_start = range_start(pd.Timestamp(mini_end), many_range)
                obj = basket_objs.get(b.id)
                if obj is not None:
                    basket_window = basket_index(obj, start=mini_start)
                    if basket_window is not None and not basket_window.empty:
                        mini.add_trace(go.Scatter(
                            x=basket_window.index, y=basket_window.values, name="Basket",
                            customdata=[b.id] * len(basket_window),
                            mode="lines", line=dict(color=BLUE, width=2.8),
                        ))
                for bm in UNIVERSAL_BENCHMARKS:
                    s = get_price(bm)
                    if s is None:
                        continue
                    r = rebase(s, mini_start)
                    if r is not None and not r.empty:
                        mini.add_trace(go.Scatter(
                            x=r.index, y=r.values, name=bm,
                            mode="lines",
                            line=dict(width=1.2, dash="dot"),
                        ))
                mini.update_yaxes(title=None)
                mini.update_xaxes(title=None, range=[mini_start, mini_end])
                plotly_layout(mini, height=250)
                card_event = st.plotly_chart(
                    mini, width="stretch", key=f"many_{b.id}_{nav_nonce}",
                    on_select="rerun", selection_mode="points",
                )
                maybe_open_from_chart(card_event, fallback_id=b.id)

                tickers = [c.ticker for c in b.constituents]
                fund = fundamentals_for(tickers)
                rows = []
                for c in b.constituents:
                    item = {"Ticker": c.ticker, "Name": c.name}
                    if fund is not None and c.ticker in fund.index:
                        f = fund.loc[c.ticker]
                        item.update({
                            "1M": f["pct_1m"] / 100 if pd.notna(f.get("pct_1m")) else None,
                            "3M": f["pct_3m"] / 100 if pd.notna(f.get("pct_3m")) else None,
                            "YTD": f["pct_ytd"] / 100 if pd.notna(f.get("pct_ytd")) else None,
                            "PE": f["pe_ttm"],
                            "Fwd PE": f.get("fwd_pe"),
                            "PEG": f.get("peg"),
                            "EPS Gr. (1Y)": f.get("eps_growth"),
                            "EV/EBITDA": f.get("ev_ebitda"),
                            "PB": f["pb"],
                            "RSI": f.get("rsi_14"),
                        })
                    rows.append(item)
                market_table(
                    pd.DataFrame(rows),
                    pct_cols=["1M", "3M", "YTD", "EPS Gr. (1Y)"],
                    formats={"PE": "{:.1f}", "Fwd PE": "{:.1f}", "PEG": "{:.2f}",
                             "EV/EBITDA": "{:.1f}", "PB": "{:.2f}", "RSI": "{:.1f}"},
                    max_rows=5,
                    compact=True,
                )

st.caption("Basket indices are buy-and-hold, fixed at inception, price return only for now.")
