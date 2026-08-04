import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_pages._shared import (basket_summary_rows, baskets_for_charts,
                               cache_banner, get_basket_index,
                               get_basket_index_stats, get_price,
                               hide_draft_on_charts, period_windows_panel,
                               UNIVERSAL_BENCHMARKS)
from src.analytics import (CHART_RANGES, basket_index, basket_index_ytd,
                           chart_range_start, perf_stats, rebase,
                           ticker_period_returns)
from src.auth import with_auth
from src.baskets import load_baskets
from src.data import fundamentals_for
from src.insights import (basket_breadth, contribution_attribution,
                          format_attribution_line, format_breadth_line,
                          triage_baskets)
from src.ui import (BLUE, PERIOD_COLORS, insight_line, market_table,
                    performance_strip, plotly_layout, share_button,
                    sort_controls, tag_filter, triage_panel, valuation_strip)
from src.valuation import (basket_valuation, fwd_pe_vs_ytd_scatter,
                           return_drawdown_heatmap, richness_label, ytd_drawdown)


def range_start(end: pd.Timestamp, choice: str) -> pd.Timestamp:
    return chart_range_start(end, choice)


def open_basket(basket_id: str) -> None:
    st.session_state["selected_basket_id"] = basket_id
    st.session_state["chart_nav_nonce"] = st.session_state.get("chart_nav_nonce", 0) + 1
    st.query_params["basket"] = basket_id
    st.switch_page("app_pages/basket_detail.py")


def relative_performance_chart(
    frame: pd.DataFrame,
    *,
    sort_by: str = "YTD",
    ascending: bool = False,
) -> go.Figure:
    """One row per basket/benchmark: YTD / 3M / 1M with fixed period colors."""
    ranked = frame[["Basket", "YTD", "3M", "1M", "_id"]].copy()
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
            "1M": stats.get("ret_1m"),
            "_id": bm,
            "_kind": "benchmark",
        })
    if bm_rows:
        ranked = pd.concat([ranked, pd.DataFrame(bm_rows)], ignore_index=True)

    col = sort_by if sort_by in ranked.columns else "YTD"
    # Semantic order: high→low puts the largest first. Plotly categorical y
    # draws the first category at the bottom, so we reverse the axis below.
    ranked = ranked.sort_values(col, ascending=ascending, na_position="last")
    patterns = ["/" if kind == "benchmark" else "" for kind in ranked["_kind"]]
    hover_kind = [
        "Benchmark" if kind == "benchmark" else "Basket"
        for kind in ranked["_kind"]
    ]
    custom = list(zip(ranked["_id"], hover_kind))

    fig = go.Figure()
    for period in ("YTD", "3M", "1M"):
        fig.add_trace(go.Bar(
            y=ranked["Basket"],
            x=ranked[period],
            name=period,
            orientation="h",
            customdata=custom,
            marker=dict(color=PERIOD_COLORS[period], pattern_shape=patterns),
            text=[f"{v:+.1%}" if pd.notna(v) else "—" for v in ranked[period]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b> · %{customdata[1]}<br>"
                + period
                + ": <b>%{x:+.1%}</b><extra>"
                + period
                + "</extra>"
            ),
        ))
    fig.add_vline(x=0, line_color="rgba(28,36,48,0.25)", line_width=1)
    fig.update_xaxes(tickformat="+.0%", title=None, automargin=True)
    # First row in `ranked` should appear at the TOP of the chart.
    fig.update_yaxes(title=None, automargin=True, autorange="reversed")
    direction = "top = low" if ascending else "top = high"
    fig.update_layout(
        title=f"Relative performance — sorted by {col} ({direction})",
        barmode="group",
        bargap=0.28,
        bargroupgap=0.12,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=20, r=60, t=60, b=20),
        showlegend=True,
        hovermode="closest",
        hoverlabel=dict(namelength=-1),
    )
    plotly_layout(fig, height=max(340, 90 + len(ranked) * 58))
    # plotly_layout resets hovermode to x-unified (good for time series);
    # ranking bars need closest so the tooltip matches the bar under the cursor.
    fig.update_layout(hovermode="closest")
    return fig


def valuation_overview_rows(baskets, summary: pd.DataFrame) -> pd.DataFrame:
    """Per-basket valuation + return fields for homepage scatter / heatmap."""
    rows = []
    for b in baskets:
        stats_row = summary[summary["_id"] == b.id]
        if stats_row.empty:
            continue
        stats_row = stats_row.iloc[0]
        tickers = [c.ticker for c in b.constituents]
        val = basket_valuation(tickers)
        ytd_path = basket_index_ytd(b)
        rows.append({
            "Basket": b.name,
            "_id": b.id,
            "YTD": stats_row["YTD"],
            "1M": stats_row["1M"],
            "3M": stats_row["3M"],
            "DD vs YTD peak": ytd_drawdown(ytd_path) if ytd_path is not None else None,
            "avg_fwd_pe": val["avg_fwd_pe"],
            "avg_trail_pe": val.get("avg_trail_pe") or val.get("cur_trail_pe"),
            "pe_5y_mean": val.get("pe_5y_mean"),
            "avg_peg": val["avg_peg"],
            "pe_5y_median": val["pe_5y_median"],
            "fwd_vs_5y_trail_pctile": val["fwd_vs_5y_trail_pctile"],
            "fwd_vs_5y_median_premium": val["fwd_vs_5y_median_premium"],
        })
    return pd.DataFrame(rows)


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
        if isinstance(custom, (list, tuple)) and len(custom) >= 4:
            basket_id = custom[3]
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

df = basket_summary_rows(for_charts=True)
if df.empty:
    if hide_draft_on_charts():
        st.info(
            "No active baskets to chart. Turn off **Hide draft baskets on charts** "
            "in the sidebar, or approve a proposal in **Basket Detail**."
        )
    else:
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

baskets = [b for b in baskets_for_charts() if b.id in set(df["_id"])]
basket_links = {
    row["Basket"]: with_auth(f"/basket_detail?basket={row['_id']}")
    for _, row in df.iterrows()
}

pct_cols = ["5D", "1M", "3M", "YTD", "1Y", "Since Inception", "Excess vs CSI300", "Max DD"]
st.caption(
    "Click a basket name to open its detail page. "
    "5D / 1M / 3M / YTD / 1Y = equal-weight average of each constituent's "
    "own return using Yahoo Finance windows "
    "(5D = 5 calendar days; 1M/3M = calendar months; 1Y/5Y = calendar years; "
    "YTD = since prior year-end close). Prices are split/dividend-adjusted. "
    "Since Inception / Excess / Max DD / Sharpe use the formal inception date."
)
period_windows_panel()
market_table(
    df.drop(columns=["_id", "_tags"]),
    pct_cols=pct_cols,
    formats={"Sharpe": "{:.2f}", "Tickers": "{:.0f}"},
    link_map={"Basket": basket_links},
    col_help={
        "Excess vs CSI300": "Since inception: basket return minus CSI300 return, both rebased at the basket's inception date.",
        "Max DD": "Maximum drawdown since inception (largest peak-to-trough decline).",
        "Sharpe": "Since inception: annualized daily return / annualized volatility (no risk-free rate).",
        "Since Inception": "Total return from the basket's inception date.",
        "5D": "Trailing 5 calendar days (Yahoo 5d), equal-weight constituents.",
        "1M": "Trailing 1 calendar month (Yahoo 1mo), equal-weight constituents.",
        "3M": "Trailing 3 calendar months (Yahoo 3mo), equal-weight constituents.",
        "YTD": "From last close before Jan 1 to latest close (adjusted total return), equal-weight constituents.",
        "1Y": "Trailing 1 calendar year (Yahoo 1y), equal-weight constituents.",
    },
)

val_rows = valuation_overview_rows(baskets, df)
triage = triage_baskets(val_rows)
st.caption(
    "Opportunity ≈ washed out + not rich · Risk ≈ rich + still near highs / hot YTD. "
    "Simple rules — not a signal."
)
triage_panel(triage["opportunities"], triage["risks"])

st.subheader("Performance")
range_choice = st.segmented_control(
    "Time range", list(CHART_RANGES), default="1Y", selection_mode="single",
) or "1Y"

fig = go.Figure()
basket_objs = {b.id: b for b in load_baskets()}
ends = []
for b in baskets:
    idx0 = get_basket_index_stats(b.id)
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
st.caption(
    "YTD / 3M / 1M share one fixed color each across baskets and benchmarks "
    "(benchmarks are hatched). Click a period to sort; click again to flip "
    "direction (top of chart = high or low). Hover a single bar for that period."
)
rel_sort, rel_asc = sort_controls(
    ["YTD", "3M", "1M"], key="rel_sort", default="YTD",
)
event_rel = st.plotly_chart(
    relative_performance_chart(df, sort_by=rel_sort, ascending=rel_asc),
    width="stretch",
    key=f"rank_rel_{nav_nonce}", on_select="rerun", selection_mode="points",
)
maybe_open_from_chart(event_rel)

if not val_rows.empty:
    st.subheader("Valuation vs returns")
    st.caption(
        "X = Forward PE level · Y = YTD return · color = 已回调 vs YTD peak "
        "(red = deep washout, teal = still near highs). "
        "Valuation richness vs own history is on each basket's valuation strip."
    )
    scatter_data = val_rows.dropna(subset=["avg_fwd_pe", "YTD"])
    if not scatter_data.empty:
        event_sc = st.plotly_chart(
            fwd_pe_vs_ytd_scatter(scatter_data), width="stretch",
            key=f"fwd_ytd_{nav_nonce}", on_select="rerun", selection_mode="points",
        )
        maybe_open_from_chart(event_sc)

    heat_data = val_rows.copy()
    if not heat_data.empty:
        st.markdown("##### Return / drawdown heatmap")
        heat_sort, heat_asc = sort_controls(
            ["1M", "3M", "YTD", "DD vs YTD peak"],
            key="heat_sort", default="YTD",
        )
        heat_sorted = heat_data.sort_values(
            heat_sort, ascending=heat_asc, na_position="last",
        )
        st.plotly_chart(
            return_drawdown_heatmap(heat_sorted),
            width="stretch",
            key=f"heat_{nav_nonce}",
        )

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
                stats_row = df[df["_id"] == b.id].iloc[0]
                title_col, open_col = st.columns([5, 1])
                with title_col:
                    st.markdown(
                        f"#### [{b.name}]({with_auth(f'/basket_detail?basket={b.id}')})"
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
                tickers = [c.ticker for c in b.constituents]
                val = basket_valuation(tickers)
                label, chip = richness_label(val.get("fwd_vs_5y_trail_pctile"))
                ytd_path = basket_index_ytd(b)
                valuation_strip(
                    val.get("avg_fwd_pe"),
                    val.get("pe_5y_mean"),
                    val.get("avg_trail_pe") or val.get("cur_trail_pe"),
                    conclusion=label,
                    conclusion_key=chip,
                    drawdown=ytd_drawdown(ytd_path) if ytd_path is not None else None,
                )
                insight_line(
                    format_breadth_line(basket_breadth(b)),
                    format_attribution_line(contribution_attribution(b, top_n=2)),
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

                fund = fundamentals_for(tickers)
                rows = []
                for c in b.constituents:
                    item = {"Ticker": c.ticker, "Name": c.name}
                    rets = ticker_period_returns(c.ticker)
                    item["1M"] = rets.get("ret_1m")
                    item["3M"] = rets.get("ret_3m")
                    item["YTD"] = rets.get("ret_ytd")
                    if fund is not None and c.ticker in fund.index:
                        f = fund.loc[c.ticker]
                        item.update({
                            "PE": f["pe_ttm"],
                            "Fwd PE": f.get("fwd_pe"),
                            "PEG": f.get("peg"),
                            "EPS Gr. (1Y)": f.get("eps_growth"),
                            "EV/EBITDA": f.get("ev_ebitda"),
                            "PB": f["pb"],
                            "RSI (14)": f.get("rsi_14"),
                        })
                    rows.append(item)
                market_table(
                    pd.DataFrame(rows),
                    pct_cols=["1M", "3M", "YTD", "EPS Gr. (1Y)"],
                    formats={"PE": "{:.1f}", "Fwd PE": "{:.1f}", "PEG": "{:.2f}",
                             "EV/EBITDA": "{:.1f}", "PB": "{:.2f}", "RSI (14)": "{:.1f}"},
                    max_rows=5,
                    compact=True,
                )

st.caption(
    "Period returns use equal-weight constituent lookback. "
    "Formal inception still anchors Since Inception / Max DD / Sharpe."
)
