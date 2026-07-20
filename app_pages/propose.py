from datetime import date
import re

import pandas as pd
import streamlit as st

from app_pages._shared import get_baskets
from src.baskets import save_basket
from src.data import quote_snapshot, search_tickers
from src.ui import internal_badge, internal_page, tag_filter

UNIVERSAL_BENCHMARKS = ["CSI300", "SPX", "NDX"]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or f"basket-{date.today().isoformat()}"


def fmt_quote(q: dict | None) -> str:
    if not q:
        return "no price yet"
    chg = q.get("chg_1d")
    chg_txt = f"  {chg:+.1%}" if chg is not None else ""
    return f"close {q['price']:.2f}{chg_txt} · {q['asof']}"


st.session_state.setdefault("proposal_constituents", [])
st.session_state.setdefault("search_results", None)
st.session_state.setdefault("search_quotes", {})
st.session_state.setdefault("last_query", "")

internal_page()
st.title("Propose a new basket")
internal_badge("Internal workflow — proposals never appear in the share view until activated.")
st.caption(
    "Benchmarks are universal (CSI300 / SPX / NDX) and the ID is auto-generated. "
    "After submitting, open the basket in Basket Detail and click Approve and activate."
)

st.markdown("### 1 · Basket basics")
name = st.text_input("Basket name", placeholder="e.g. National Team Floor Plays")
author = st.text_input("Proposed by", placeholder="your name")
thesis = st.text_area(
    "Thesis / narrative", height=150,
    placeholder="Why does this basket exist? What is the catalyst, what would make us wrong?",
)
existing_tags = sorted({t for b in get_baskets() for t in b.tags})
st.caption("Tags — tap to select; type below to add a new one")
picked = tag_filter(existing_tags, key="propose_tags") if existing_tags else []
new_tag = st.text_input("New tag (optional)", placeholder="e.g. soft-landing")
tags = list(dict.fromkeys([*picked, new_tag.strip()] if new_tag.strip() else picked))
newsletter = st.text_input("Related newsletter URL (optional)")

st.markdown("### 2 · Add constituents")
st.caption(
    "Search tries, in order: direct code → EODHD HK/A/US symbol lists → EODHD search API → "
    "basket YAML names → local fundamentals cache. "
    "HK (e.g. Pop Mart) and US / China ADRs (e.g. TCOM) resolve via EODHD; "
    "price history + Fwd PE / PEG come from EODHD, PE/PB from Baidu via akshare (A/HK)."
)
search_col, btn_col = st.columns([4, 1])
with search_col:
    query = st.text_input(
        "Search by ticker or company name",
        placeholder="e.g. Pop Mart, 09992, BYD, TCOM, 002594",
        label_visibility="collapsed",
    )
with btn_col:
    do_search = st.button("Search", type="primary", width="stretch")

if do_search and query.strip():
    with st.spinner("Searching via EODHD…"):
        results = search_tickers(query)
        quotes = {}
        for item in results:
            quotes[item["ticker"]] = quote_snapshot(item["ticker"])
        st.session_state.search_results = results
        st.session_state.search_quotes = quotes
        st.session_state.last_query = query
elif do_search:
    st.session_state.search_results = None
    st.warning("Type a ticker or company name first.")

results = st.session_state.search_results
quotes = st.session_state.search_quotes
if results is not None:
    in_draft = {c["ticker"] for c in st.session_state.proposal_constituents}
    if not results:
        st.error(
            f'No match for "{st.session_state.last_query}". '
            "Try another spelling, the numeric code, or the English company name."
        )
    else:
        st.success(
            f'{len(results)} match(es) for "{st.session_state.last_query}" — '
            "check the close price, then click ＋ to add."
        )
        for i, item in enumerate(results):
            q = quotes.get(item["ticker"])
            cols = st.columns([1.3, 2.4, 2.2, 0.8])
            cols[0].code(item["ticker"])
            cols[1].write(item["name"])
            cols[2].caption(fmt_quote(q))
            if item["ticker"] in in_draft:
                cols[3].button("Added", key=f"added_{i}", disabled=True)
            elif cols[3].button("＋ Add", key=f"add_{i}_{item['ticker']}"):
                st.session_state.proposal_constituents.append({
                    "ticker": item["ticker"],
                    "name": item["name"],
                    "weight": 1.0,
                    "rationale": "",
                })
                st.session_state[f"prop_nm_{item['ticker']}"] = item["name"]
                st.session_state[f"prop_wt_{item['ticker']}"] = 1.0
                st.session_state[f"prop_nt_{item['ticker']}"] = ""
                st.toast(f"Added {item['name']} ({item['ticker']})")
                st.rerun()

st.markdown("### 3 · Draft basket")
draft = st.session_state.proposal_constituents
if not draft:
    st.info("No constituents yet — search above and add them one by one.")
else:
    st.caption(
        f"{len(draft)} constituent(s). Weight defaults to 1 (equal-weighted; "
        "values are normalized). Use Remove to drop a name."
    )
    hdr = st.columns([1.4, 2.2, 1.0, 3.2, 0.9])
    hdr[0].caption("Ticker")
    hdr[1].caption("Name")
    hdr[2].caption("Weight")
    hdr[3].caption("Constituent rationale")
    hdr[4].caption("")
    for row in list(draft):
        ticker = row["ticker"]
        st.session_state.setdefault(f"prop_nm_{ticker}", row.get("name") or ticker)
        st.session_state.setdefault(
            f"prop_wt_{ticker}",
            float(1.0 if row.get("weight") is None else row["weight"]),
        )
        st.session_state.setdefault(f"prop_nt_{ticker}", row.get("rationale") or "")
        cols = st.columns([1.4, 2.2, 1.0, 3.2, 0.9])
        cols[0].code(ticker)
        cols[1].text_input("Name", key=f"prop_nm_{ticker}", label_visibility="collapsed")
        cols[2].number_input(
            "Weight", min_value=0.0, step=1.0, key=f"prop_wt_{ticker}",
            label_visibility="collapsed",
        )
        cols[3].text_input(
            "Rationale", key=f"prop_nt_{ticker}", label_visibility="collapsed",
        )
        if cols[4].button("Remove", key=f"prop_rm_{ticker}", width="stretch"):
            st.session_state.proposal_constituents = [
                r for r in st.session_state.proposal_constituents if r["ticker"] != ticker
            ]
            for prefix in ("prop_nm_", "prop_wt_", "prop_nt_"):
                st.session_state.pop(f"{prefix}{ticker}", None)
            st.toast(f"Removed {ticker}")
            st.rerun()
    # Keep draft list in sync with widget values for submit.
    synced = []
    for row in st.session_state.proposal_constituents:
        ticker = row["ticker"]
        synced.append({
            "ticker": ticker,
            "name": st.session_state.get(f"prop_nm_{ticker}", row.get("name") or ticker),
            "weight": st.session_state.get(f"prop_wt_{ticker}", row.get("weight") or 1.0),
            "rationale": st.session_state.get(f"prop_nt_{ticker}", row.get("rationale") or ""),
        })
    st.session_state.proposal_constituents = synced

st.markdown("### 4 · Submit")
if st.button("Create proposal", type="primary", disabled=not (name and draft)):
    basket_id = slugify(name)
    existing_ids = {b.id for b in get_baskets()}
    base_id, suffix = basket_id, 2
    while basket_id in existing_ids:
        basket_id = f"{base_id}-{suffix}"
        suffix += 1

    today = date.today().isoformat()
    data = {
        "id": basket_id,
        "name": name,
        "status": "proposed",
        "author": author,
        "created": today,
        "inception": today,
        "tags": list(tags),
        "thesis": thesis,
        "benchmarks": UNIVERSAL_BENCHMARKS,
        "newsletters": ([{"title": "Related piece", "url": newsletter, "date": today}]
                        if newsletter else []),
        "watchpoints": [],
        "team_charts": [],
        "constituents": [
            {"ticker": c["ticker"], "name": c["name"],
             "weight": 1.0 if c.get("weight") is None else c.get("weight"),
             "note": c.get("rationale", "")}
            for c in st.session_state.proposal_constituents
        ],
    }
    save_basket(data, refresh_data=True)
    st.cache_data.clear()
    for row in st.session_state.proposal_constituents:
        ticker = row["ticker"]
        for prefix in ("prop_nm_", "prop_wt_", "prop_nt_"):
            st.session_state.pop(f"{prefix}{ticker}", None)
    st.session_state.proposal_constituents = []
    st.session_state.search_results = None
    st.session_state.search_quotes = {}
    from src.auth import flash_success
    flash_success(
        f"Proposal “{name}” saved. Open Basket Detail to review, "
        "then Approve and activate."
    )
    st.rerun()
if not name:
    st.caption("Submit is enabled once the basket has a name and at least one constituent.")
