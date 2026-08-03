import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_pages._shared import (STATUS_BADGE, cache_banner, get_basket_index,
                               get_basket_index_stats, get_baskets, get_price,
                               UNIVERSAL_BENCHMARKS)
from src.analytics import basket_index_ytd, basket_perf_stats, component_indices, rebase, ticker_period_returns
from src.auth import flash_success
from src.baskets import delete_basket, update_basket_fields
from src.data import fundamentals_for, merge_basket_news, quote_snapshot, search_tickers
from src.insights import (basket_breadth, contribution_attribution,
                          format_attribution_line, format_breadth_line)
from src.ui import (BLUE, insight_line, internal_badge, internal_heading, market_table,
                    metric_grid, news_feed, plotly_layout, share_button, tag_filter,
                    valuation_strip)
from src.valuation import (basket_valuation, basket_valuation_figure,
                           richness_label, ytd_drawdown)

baskets = {b.id: b for b in get_baskets()}
if not baskets:
    st.info("No baskets defined yet.")
    st.stop()

# Prefer deep-link from Overview (query param / session), then fall back to first basket.
requested = (
    st.query_params.get("basket")
    or st.session_state.get("selected_basket_id")
)
names = {b.name: b.id for b in baskets.values()}
name_list = list(names)
default_ix = 0
if requested and requested in baskets:
    default_name = baskets[requested].name
    if default_name in name_list:
        default_ix = name_list.index(default_name)

choice = st.selectbox("Basket", name_list, index=default_ix)
b = baskets[names[choice]]
st.session_state["selected_basket_id"] = b.id
st.query_params["basket"] = b.id

title_col, btn_col = st.columns([4, 1])
with title_col:
    st.title(b.name)
with btn_col:
    share_button("Share view", f"?share=basket&basket={b.id}")
tag_line = " · ".join(f"`{t}`" for t in b.tags) if b.tags else "no tags"
st.markdown(
    f"{STATUS_BADGE.get(b.status, b.status)} · inception **{b.inception}** · {tag_line}"
)
tickers = [c.ticker for c in b.constituents]
cache_banner(tickers)

left, right = st.columns([1.6, 1])
with left:
    st.markdown("#### Thesis")
    st.markdown(b.thesis)
with right:
    st.markdown("#### Published in")
    if b.newsletters:
        for n in b.newsletters:
            url = n.get("url") or ""
            date = n.get("date") or ""
            label = n.get("title") or url or "Newsletter"
            if url:
                st.markdown(f"- [{label}]({url})" + (f" — {date}" if date else ""))
            else:
                st.markdown(f"- {label}" + (f" — {date}" if date else ""))
    else:
        st.caption("No linked newsletter yet.")

idx = get_basket_index(b.id)
idx_stats = get_basket_index_stats(b.id)
ytd_path = basket_index_ytd(b)

st.markdown("#### Performance vs benchmarks")
if idx_stats is None or idx_stats.empty:
    st.warning("No cached price data for this basket yet — run an update on the Data & Update page.")
else:
    stats = basket_perf_stats(b)
    metric_grid([
        ("1W", stats.get("ret_1w"), "pct"),
        ("1M", stats.get("ret_1m"), "pct"),
        ("3M", stats.get("ret_3m"), "pct"),
        ("YTD", stats.get("ret_ytd"), "pct"),
        ("1Y", stats.get("ret_1y"), "pct"),
        ("Since", stats.get("ret_inception"), "pct"),
        ("Sharpe", stats.get("sharpe"), "ratio"),
        ("Max DD", stats.get("max_dd"), "pct"),
    ])
    st.caption(
        "1W / 1M / 3M / YTD / 1Y = equal-weight average of each constituent's "
        "own return (Google windows: 1M=4w, 3M=13w, 1Y=52w; YTD from prior "
        "year-end). Since / Sharpe / Max DD = from formal inception."
    )

    chart_mode = st.radio(
        "Price chart",
        ["Basket vs universal benchmarks", "Show basket components"],
        horizontal=True,
    )
    chart_idx = idx if idx is not None and not idx.empty else idx_stats
    fig = go.Figure()
    if chart_mode.startswith("Basket"):
        fig.add_trace(go.Scatter(x=chart_idx.index, y=chart_idx.values, name=b.name, mode="lines",
                                 line=dict(width=3, color=BLUE)))
        for bm in UNIVERSAL_BENCHMARKS:
            s = get_price(bm)
            if s is None:
                continue
            r = rebase(s, chart_idx.index[0])
            if r is not None:
                fig.add_trace(go.Scatter(x=r.index, y=r.values, name=bm, mode="lines",
                                         line=dict(dash="dash", width=1.6)))
    else:
        fig.add_trace(go.Scatter(x=chart_idx.index, y=chart_idx.values, name=b.name,
                                 mode="lines", line=dict(width=3, color=BLUE)))
        for bm in UNIVERSAL_BENCHMARKS:
            s = get_price(bm)
            if s is None:
                continue
            r = rebase(s, chart_idx.index[0])
            if r is not None:
                fig.add_trace(go.Scatter(x=r.index, y=r.values, name=bm,
                                         mode="lines",
                                         line=dict(dash="dash", width=1.4)))
        comps = component_indices(b)
        if comps is not None:
            for col in comps.columns:
                fig.add_trace(go.Scatter(x=comps.index, y=comps[col], name=col,
                                         mode="lines", line=dict(width=1.8)))
    fig.update_yaxes(title="Normalized price (100 = start)")
    plotly_layout(fig, height=500)
    st.plotly_chart(fig, width="stretch")

st.markdown("#### Essential data")
fund = fundamentals_for(tickers)
weights = b.weights

rows = []
for c in b.constituents:
    row = {
        "Ticker": c.ticker,
        "Name": c.name,
        "Market": c.market,
        "Weight": weights.get(c.ticker),
        "Price": None,
        "1M": None,
        "3M": None,
        "YTD": None,
        "Fwd PE": None,
        "PEG": None,
        "EPS Gr. (1Y)": None,
        "P/E": None,
        "P/B": None,
        "EV/EBITDA": None,
        "RSI (14)": None,
    }
    rets = ticker_period_returns(c.ticker)
    row["1M"] = rets.get("ret_1m")
    row["3M"] = rets.get("ret_3m")
    row["YTD"] = rets.get("ret_ytd")
    if fund is not None and c.ticker in fund.index:
        f = fund.loc[c.ticker]
        row.update({
            "Price": f["price"],
            "Fwd PE": f.get("fwd_pe"),
            "PEG": f.get("peg"),
            "EPS Gr. (1Y)": f.get("eps_growth"),
            "P/E": f["pe_ttm"],
            "P/B": f["pb"],
            "EV/EBITDA": f.get("ev_ebitda"),
            "RSI (14)": f.get("rsi_14"),
        })
        # Prefer live close from price cache when fundamentals price is stale.
        if rets.get("asof") is not None:
            s = get_price(c.ticker)
            if s is not None and not s.empty:
                row["Price"] = float(s.iloc[-1])
    rows.append(row)

constituents_df = pd.DataFrame(rows)
market_table(
    constituents_df,
    pct_cols=["Weight", "1M", "3M", "YTD", "EPS Gr. (1Y)"],
    formats={
        "Price": "{:.2f}", "Fwd PE": "{:.1f}", "PEG": "{:.2f}",
        "P/E": "{:.1f}", "P/B": "{:.2f}", "EV/EBITDA": "{:.1f}", "RSI (14)": "{:.1f}",
    },
    col_help={
        "RSI (14)": "14-period Wilder RSI on adjusted close (computed locally from cached prices).",
    },
)
st.caption("EPS Gr. (1Y) = EODHD consensus forward EPS growth (+1y). No multi-year CAGR field.")

st.markdown("#### Valuation")
st.caption(
    "Current Forward PE from EODHD Fundamentals. 5y context uses reconstructed "
    "Trailing PE (month-end price ÷ TTM EPS, Baidu fallback). Fwd %ile = where today's "
    "Forward PE sits in that trail-PE distribution (high = expensive vs own history)."
)
val = basket_valuation(tickers)
label, chip = richness_label(val.get("fwd_vs_5y_trail_pctile"))
dd = ytd_drawdown(ytd_path) if ytd_path is not None else None
valuation_strip(
    val.get("avg_fwd_pe"),
    val.get("pe_5y_mean"),
    val.get("avg_trail_pe") or val.get("cur_trail_pe"),
    conclusion=label,
    conclusion_key=chip,
    drawdown=dd,
)
insight_line(
    format_breadth_line(basket_breadth(b)),
    format_attribution_line(contribution_attribution(b, top_n=2)),
)

def _fmt_pe(v, digits=1):
    return f"{v:.{digits}f}" if v is not None and pd.notna(v) else "—"

def _fmt_pctile(v):
    return f"{v:.0f}" if v is not None and pd.notna(v) else "—"

def _fmt_prem(v):
    return f"{v:+.0%}" if v is not None and pd.notna(v) else "—"

kpi_cols = st.columns(4)
kpi_cols[0].metric("Avg PEG", _fmt_pe(val.get("avg_peg"), 2))
kpi_cols[1].metric("5y Trail med", _fmt_pe(val.get("pe_5y_median")))
kpi_cols[2].metric("Fwd vs 5y med", _fmt_prem(val.get("fwd_vs_5y_median_premium")))
kpi_cols[3].metric("Fwd %ile", _fmt_pctile(val.get("fwd_vs_5y_trail_pctile")))

pe_hist = val.get("pe_hist")
has_pe = pe_hist is not None and not getattr(pe_hist, "empty", True)
val_chart_idx = idx_stats if idx_stats is not None and not idx_stats.empty else idx
if val_chart_idx is not None and not val_chart_idx.empty and has_pe:
    st.plotly_chart(
        basket_valuation_figure(
            val_chart_idx,
            pe_hist,
            avg_fwd_pe=val.get("avg_fwd_pe"),
            avg_trail_pe=val.get("avg_trail_pe") or val.get("cur_trail_pe"),
            stats=val,
        ),
        width="stretch",
    )
    st.caption(
        "左图：从今年高点回撤了多少（峰值=100）。"
        "中图：5年 Trailing PE 轨迹；橙带=25–75分位，橙虚线=中位数，红钻=今日 Forward PE。"
        "右图：今日 Fwd/Trail 落在5年 Trail PE 区间的位置。"
    )
elif not has_pe:
    st.info(
        "Trailing PE history not cached yet — run **Data & Update** "
        "(or `update_data.py`) to fetch earnings history and rebuild PE paths."
    )

st.markdown("#### Constituent news")
news_count_key = f"news_count_{b.id}"
news_cache_key = f"news_cache_{b.id}"
st.session_state.setdefault(news_count_key, 8)
st.caption("Headlines from EODHD and Eastmoney (akshare), merged for all basket tickers.")
if news_cache_key not in st.session_state:
    with st.spinner("Fetching news…"):
        st.session_state[news_cache_key] = merge_basket_news(tickers, limit_per_ticker=5)

cached_news = st.session_state.get(news_cache_key) or []
shown = st.session_state[news_count_key]
news_feed(cached_news, start=0, count=shown)
if shown < len(cached_news):
    if st.button(f"Show more ({len(cached_news) - shown} left)", key=f"more_news_{b.id}"):
        st.session_state[news_count_key] = min(shown + 8, len(cached_news))
        st.rerun()

with st.expander("Constituent rationale", expanded=False):
    st.caption("These notes come from each constituent's rationale field in the basket definition.")
    for c in b.constituents:
        st.markdown(f"- **{c.name} ({c.ticker})**: {c.note or 'No rationale yet.'}")

st.markdown("#### Watchpoints")
internal_badge("Manually edited for now; later this becomes the AI-updated monitoring checklist.")
internal_heading("What should we keep watching for this basket?")
current_watchpoints = "\n".join(f"- {item}" for item in b.watchpoints) if b.watchpoints else ""
watch_text = st.text_area(
    "What should we keep watching for this basket?",
    value=current_watchpoints,
    height=140,
    label_visibility="collapsed",
    placeholder="- Policy catalyst to monitor\n- Valuation level where we get more cautious\n- Data series / company KPI to update monthly",
)

if st.button("Save watchpoints", type="primary"):
    watchpoints = [
        line.strip()[2:].strip() if line.strip().startswith("- ") else line.strip()
        for line in watch_text.splitlines()
        if line.strip()
    ]
    update_basket_fields(b.id, {"watchpoints": watchpoints})
    st.cache_data.clear()
    flash_success("Saved watchpoints.")
    st.rerun()

st.divider()
with st.expander("Internal — edit tags, newsletters, definition", expanded=False):
    internal_badge(
        "Approve proposals, edit tags / newsletters / definition, or delete."
    )
    st.caption(
        "Any teammate with the password can activate a proposal or move an "
        "active basket back to proposed. Tags, newsletters, and basket "
        "definition are editable below."
    )
    if b.status == "proposed":
        if st.button("Approve and activate basket", type="primary"):
            update_basket_fields(b.id, {"status": "active"})
            st.cache_data.clear()
            flash_success(f"“{b.name}” is now Active.")
            st.rerun()
    elif b.status == "active":
        if st.button("Move back to proposed"):
            update_basket_fields(b.id, {"status": "proposed"})
            st.cache_data.clear()
            flash_success(f"“{b.name}” is now Proposed (draft).")
            st.rerun()

    internal_heading("Tags")
    all_tags = sorted({t for basket in get_baskets() for t in basket.tags} | set(b.tags))
    picked_tags = tag_filter(all_tags, key=f"edit_tags_{b.id}", default=list(b.tags))
    new_tag = st.text_input("Add a new tag", key=f"new_tag_{b.id}",
                            placeholder="e.g. soft-landing")
    edit_tags = list(dict.fromkeys(
        [*(picked_tags or []), new_tag.strip()] if new_tag.strip() else list(picked_tags or [])
    ))

    internal_heading("Related newsletters")
    st.caption("Keep a running list of posts that mention this basket — URL + publish date.")
    nl_rows = [
        {"url": str(item.get("url") or ""), "date": str(item.get("date") or "")[:10]}
        for item in (b.newsletters or [])
    ] or [{"url": "", "date": ""}]
    nl_df = pd.DataFrame(nl_rows)
    nl_df["url"] = nl_df["url"].astype(str).replace({"nan": "", "None": ""})
    nl_df["date"] = nl_df["date"].astype(str).replace({"nan": "", "NaT": "", "None": ""})
    edited_nl = st.data_editor(
        nl_df,
        hide_index=True,
        width="stretch",
        num_rows="dynamic",
        key=f"nl_editor_{b.id}",
        column_config={
            "url": st.column_config.TextColumn("URL", width="large"),
            "date": st.column_config.TextColumn("Publish date", width="small",
                                               help="YYYY-MM-DD"),
        },
    )

    if st.button("Save tags & newsletters", type="primary", key=f"save_meta_{b.id}"):
        newsletters = []
        frame = edited_nl if isinstance(edited_nl, pd.DataFrame) else pd.DataFrame(edited_nl)
        for row in frame.to_dict("records"):
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            newsletters.append({
                "title": "Related piece",
                "url": url,
                "date": str(row.get("date") or "").strip()[:10],
            })
        update_basket_fields(
            b.id,
            {
                "tags": edit_tags,
                "newsletters": newsletters,
            },
        )
        st.cache_data.clear()
        flash_success("Tags and newsletters saved.")
        st.rerun()

    st.divider()
    internal_heading("Basket definition")
    edit_name = st.text_input("Name", value=b.name, key=f"edit_name_{b.id}")
    edit_thesis = st.text_area("Thesis", value=b.thesis, height=180, key=f"edit_thesis_{b.id}")
    edit_inception = st.text_input(
        "Inception (YYYY-MM-DD)", value=b.inception, key=f"edit_inception_{b.id}",
    )

    const_key = f"edit_const_{b.id}"

    def _seed_const_fields(rows: list[dict]) -> None:
        for row in rows:
            ticker = row["ticker"]
            st.session_state[f"edit_nm_{b.id}_{ticker}"] = row.get("name") or ticker
            st.session_state[f"edit_wt_{b.id}_{ticker}"] = float(
                1.0 if row.get("weight") is None else row["weight"]
            )
            st.session_state[f"edit_nt_{b.id}_{ticker}"] = row.get("note") or ""

    def _clear_const_fields(ticker: str) -> None:
        for prefix in ("edit_nm_", "edit_wt_", "edit_nt_"):
            st.session_state.pop(f"{prefix}{b.id}_{ticker}", None)

    if st.session_state.get("edit_const_basket") != b.id:
        rows = [
            {
                "ticker": c.ticker,
                "name": c.name,
                "weight": 1.0 if c.weight is None else c.weight,
                "note": c.note,
            }
            for c in b.constituents
        ]
        st.session_state[const_key] = rows
        _seed_const_fields(rows)
        st.session_state["edit_const_basket"] = b.id

    internal_heading("Add constituents")
    st.caption("Search by ticker or company name — same sources as Propose a Basket.")
    search_col, btn_col = st.columns([4, 1])
    with search_col:
        edit_query = st.text_input(
            "Search tickers",
            placeholder="e.g. Pop Mart, 09992, BYD, TCOM, 002594",
            key=f"edit_search_q_{b.id}",
            label_visibility="collapsed",
        )
    with btn_col:
        do_edit_search = st.button("Search", key=f"edit_search_btn_{b.id}", type="secondary",
                                   width="stretch")

    if do_edit_search and edit_query.strip():
        with st.spinner("Searching…"):
            results = search_tickers(edit_query)
            quotes = {item["ticker"]: quote_snapshot(item["ticker"]) for item in results}
            st.session_state[f"edit_search_results_{b.id}"] = results
            st.session_state[f"edit_search_quotes_{b.id}"] = quotes
    elif do_edit_search:
        st.warning("Type a ticker or company name first.")

    edit_results = st.session_state.get(f"edit_search_results_{b.id}")
    edit_quotes = st.session_state.get(f"edit_search_quotes_{b.id}", {})
    if edit_results is not None:
        in_basket = {row["ticker"] for row in st.session_state[const_key]}
        if not edit_results:
            st.error(f'No match for "{edit_query}". Try another spelling or code.')
        else:
            for i, item in enumerate(edit_results):
                q = edit_quotes.get(item["ticker"])
                qtxt = "no price yet"
                if q:
                    chg = q.get("chg_1d")
                    chg_txt = f"  {chg:+.1%}" if chg is not None else ""
                    qtxt = f"close {q['price']:.2f}{chg_txt} · {q['asof']}"
                cols = st.columns([1.3, 2.4, 2.2, 0.8])
                cols[0].code(item["ticker"])
                cols[1].write(item["name"])
                cols[2].caption(qtxt)
                if item["ticker"] in in_basket:
                    cols[3].button("Added", key=f"edit_added_{b.id}_{i}", disabled=True)
                elif cols[3].button("＋ Add", key=f"edit_add_{b.id}_{i}"):
                    new_row = {
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "weight": 1.0,
                        "note": "",
                    }
                    st.session_state[const_key].append(new_row)
                    _seed_const_fields([new_row])
                    st.toast(f"Added {item['name']} ({item['ticker']})")
                    st.rerun()

    internal_heading("Current constituents")
    draft = st.session_state[const_key]
    if not draft:
        st.info("No constituents — search above and add at least one.")
    else:
        st.caption(
            f"{len(draft)} name(s). Edit weight / rationale inline; "
            "use Remove to drop a ticker (does not rely on the table trash icon)."
        )
        hdr = st.columns([1.4, 2.2, 1.0, 3.2, 0.9])
        hdr[0].caption("Ticker")
        hdr[1].caption("Name")
        hdr[2].caption("Weight")
        hdr[3].caption("Constituent rationale")
        hdr[4].caption("")
        for row in list(draft):
            ticker = row["ticker"]
            cols = st.columns([1.4, 2.2, 1.0, 3.2, 0.9])
            cols[0].code(ticker)
            cols[1].text_input(
                "Name",
                key=f"edit_nm_{b.id}_{ticker}",
                label_visibility="collapsed",
            )
            cols[2].number_input(
                "Weight",
                min_value=0.0,
                step=1.0,
                key=f"edit_wt_{b.id}_{ticker}",
                label_visibility="collapsed",
                help="Equal-weight baskets use 1; values are normalized on save.",
            )
            cols[3].text_input(
                "Note",
                key=f"edit_nt_{b.id}_{ticker}",
                label_visibility="collapsed",
            )
            if cols[4].button("Remove", key=f"edit_rm_{b.id}_{ticker}", width="stretch"):
                st.session_state[const_key] = [
                    r for r in st.session_state[const_key] if r["ticker"] != ticker
                ]
                _clear_const_fields(ticker)
                st.toast(f"Removed {ticker}")
                st.rerun()

    if st.button("Save basket definition", type="primary", key=f"save_def_{b.id}"):
        from src.baskets import _clean_constituents

        records = []
        for row in st.session_state[const_key]:
            ticker = row["ticker"]
            records.append({
                "ticker": ticker,
                "name": st.session_state.get(f"edit_nm_{b.id}_{ticker}", row.get("name") or ticker),
                "weight": st.session_state.get(f"edit_wt_{b.id}_{ticker}", row.get("weight") or 1.0),
                "note": st.session_state.get(f"edit_nt_{b.id}_{ticker}", row.get("note") or ""),
            })
        records = _clean_constituents(records)
        if not records:
            st.error("A basket needs at least one constituent.")
        else:
            update_basket_fields(
                b.id,
                {
                    "name": edit_name,
                    "thesis": edit_thesis,
                    "inception": edit_inception,
                    "constituents": records,
                },
            )
            st.cache_data.clear()
            st.session_state.pop(const_key, None)
            st.session_state.pop("edit_const_basket", None)
            flash_success("Basket definition updated.")
            st.rerun()

    confirm = st.text_input("To delete, type the basket ID", placeholder=b.id)
    if st.button("Delete basket", type="secondary", disabled=confirm != b.id):
        delete_basket(b.id)
        st.cache_data.clear()
        flash_success(f"Deleted “{b.name}”.")
        st.switch_page("app_pages/overview.py")
