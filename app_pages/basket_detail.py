import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_pages._shared import (STATUS_BADGE, cache_banner, get_basket_index,
                               get_baskets, get_price, UNIVERSAL_BENCHMARKS)
from src.analytics import component_indices, fmt_pct, perf_stats, rebase
from src.auth import flash_success
from src.baskets import delete_basket, update_basket_fields
from src.chart_registry import (chart_description, chart_title, load_chart_modules,
                                render_chart)
from src.data import fundamentals_for
from src.ui import (BLUE, internal_badge, internal_heading, market_table,
                    metric_grid, plotly_layout, share_button, tag_filter)

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

st.markdown("#### Performance vs benchmarks")
if idx is None or idx.empty:
    st.warning("No cached price data for this basket yet — run an update on the Data & Update page.")
else:
    stats = perf_stats(idx)
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

    chart_mode = st.radio(
        "Price chart",
        ["Basket vs universal benchmarks", "Show basket components"],
        horizontal=True,
    )
    fig = go.Figure()
    if chart_mode.startswith("Basket"):
        fig.add_trace(go.Scatter(x=idx.index, y=idx.values, name=b.name, mode="lines",
                                 line=dict(width=3, color=BLUE)))
        for bm in UNIVERSAL_BENCHMARKS:
            s = get_price(bm)
            if s is None:
                continue
            r = rebase(s, idx.index[0])
            if r is not None:
                fig.add_trace(go.Scatter(x=r.index, y=r.values, name=bm, mode="lines",
                                         line=dict(dash="dash", width=1.6)))
    else:
        fig.add_trace(go.Scatter(x=idx.index, y=idx.values, name=b.name,
                                 mode="lines", line=dict(width=3, color=BLUE)))
        for bm in UNIVERSAL_BENCHMARKS:
            s = get_price(bm)
            if s is None:
                continue
            r = rebase(s, idx.index[0])
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
        "RSI": None,
    }
    if fund is not None and c.ticker in fund.index:
        f = fund.loc[c.ticker]
        row.update({
            "Price": f["price"],
            "1M": f["pct_1m"] / 100 if pd.notna(f.get("pct_1m")) else None,
            "3M": f["pct_3m"] / 100 if pd.notna(f.get("pct_3m")) else None,
            "YTD": f["pct_ytd"] / 100 if pd.notna(f.get("pct_ytd")) else None,
            "Fwd PE": f.get("fwd_pe"),
            "PEG": f.get("peg"),
            "EPS Gr. (1Y)": f.get("eps_growth"),
            "P/E": f["pe_ttm"],
            "P/B": f["pb"],
            "EV/EBITDA": f.get("ev_ebitda"),
            "RSI": f.get("rsi_14"),
        })
    rows.append(row)

constituents_df = pd.DataFrame(rows)
market_table(
    constituents_df,
    pct_cols=["Weight", "1M", "3M", "YTD", "EPS Gr. (1Y)"],
    formats={
        "Price": "{:.2f}", "Fwd PE": "{:.1f}", "PEG": "{:.2f}",
        "P/E": "{:.1f}", "P/B": "{:.2f}", "EV/EBITDA": "{:.1f}", "RSI": "{:.1f}",
    },
)
st.caption("EPS Gr. (1Y) = EODHD consensus forward EPS growth (+1y). No multi-year CAGR field.")

chart_modules = load_chart_modules()
chart_options = {chart_title(mod): slug for slug, mod in chart_modules}
attached = [(slug, mod) for slug, mod in chart_modules if slug in b.team_charts]
if attached:
    st.markdown("#### Team charts for this basket")
    cols = st.columns(2)
    for i, (_, mod) in enumerate(attached):
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f"##### {chart_title(mod)}")
                desc = chart_description(mod)
                if desc:
                    st.caption(desc)
                render_chart(mod, basket=b, compact=True)

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

saved_titles = [title for title, slug in chart_options.items() if slug in b.team_charts]
internal_heading("Attach team charts to this basket")
selected_titles = st.multiselect(
    "Attach team charts to this basket",
    list(chart_options),
    default=saved_titles,
    label_visibility="collapsed",
)

if st.button("Save watchpoints / chart links", type="primary"):
    watchpoints = [
        line.strip()[2:].strip() if line.strip().startswith("- ") else line.strip()
        for line in watch_text.splitlines()
        if line.strip()
    ]
    update_basket_fields(
        b.id,
        {"watchpoints": watchpoints,
         "team_charts": [chart_options[t] for t in selected_titles]},
    )
    st.cache_data.clear()
    flash_success("Saved watchpoints and chart links.")
    st.rerun()

st.divider()
with st.expander("Internal — edit tags, newsletters, definition", expanded=False):
    internal_badge("Approve proposals, edit tags / newsletters / definition, or delete.")
    st.caption(
        "Any teammate with the password can activate a proposal. "
        "Tags and newsletters can be updated anytime."
    )
    if b.status == "proposed":
        if st.button("Approve and activate basket", type="primary"):
            update_basket_fields(b.id, {"status": "active"})
            st.cache_data.clear()
            flash_success(f"“{b.name}” is now Active.")
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
        update_basket_fields(b.id, {"tags": edit_tags, "newsletters": newsletters})
        st.cache_data.clear()
        flash_success("Tags and newsletters saved.")
        st.rerun()

    st.divider()
    edit_mode = st.toggle("Edit basket definition")
    if edit_mode:
        edit_name = st.text_input("Name", value=b.name)
        edit_thesis = st.text_area("Thesis", value=b.thesis, height=180)
        edit_inception = st.text_input("Inception (YYYY-MM-DD)", value=b.inception)
        editable = pd.DataFrame([
            {
                "ticker": c.ticker,
                "name": c.name,
                "weight": 1.0 if c.weight is None else c.weight,
                "note": c.note,
            }
            for c in b.constituents
        ])
        edited = st.data_editor(
            editable,
            hide_index=True,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "ticker": st.column_config.TextColumn("Ticker"),
                "name": st.column_config.TextColumn("Name"),
                "weight": st.column_config.NumberColumn(
                    "Weight", min_value=0.0, step=1.0,
                    help="Equal-weight baskets use 1 for every name; values are normalized.",
                ),
                "note": st.column_config.TextColumn("Constituent rationale"),
            },
        )
        if st.button("Save basket edits", type="primary"):
            records = edited.to_dict("records") if isinstance(edited, pd.DataFrame) else edited
            for row in records:
                if row.get("weight") is None or (isinstance(row.get("weight"), float)
                                                 and pd.isna(row["weight"])):
                    row["weight"] = 1.0
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
            flash_success("Basket definition updated.")
            st.rerun()

    confirm = st.text_input("To delete, type the basket ID", placeholder=b.id)
    if st.button("Delete basket", type="secondary", disabled=confirm != b.id):
        delete_basket(b.id)
        st.cache_data.clear()
        flash_success(f"Deleted “{b.name}”.")
        st.switch_page("app_pages/overview.py")
