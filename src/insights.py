"""Concise investment insights: triage, breadth, contribution attribution."""

from __future__ import annotations

import pandas as pd

from .baskets import Basket
from .data import fundamentals_for, load_price
from .valuation import (_safe_pe, pe_stats_vs_history, richness_label,
                        stock_pe_history, ytd_drawdown)

DEEP_DD = -0.20  # component "深回调" threshold vs YTD peak
CHEAP_PCTILE = 40
RICH_PCTILE = 70


def component_period_returns(basket: Basket, *, period: str = "1M") -> list[dict]:
    """Per-constituent period return + weight (for attribution)."""
    from .analytics import _series_period_return

    weights = basket.weights
    rows = []
    for c in basket.constituents:
        s = load_price(c.ticker)
        ret = (
            _series_period_return(s, period=period)
            if s is not None else None
        )
        rows.append({
            "ticker": c.ticker,
            "name": c.name,
            "weight": weights.get(c.ticker, 0.0),
            "ret": ret,
        })
    return rows


def contribution_attribution(
    basket: Basket,
    *,
    period: str = "1M",
    days: int | None = None,  # noqa: ARG001 — legacy kw ignored
    months: int | None = None,  # noqa: ARG001 — legacy kw ignored
    top_n: int = 2,
) -> dict:
    """Top / bottom contributors by weight × return (equal-weight friendly)."""
    rows = component_period_returns(basket, period=period)
    scored = []
    for r in rows:
        if r["ret"] is None:
            continue
        contrib = float(r["weight"]) * float(r["ret"])
        scored.append({**r, "contrib": contrib})
    if not scored:
        return {"leaders": [], "laggards": [], "period": period}

    scored.sort(key=lambda x: x["contrib"], reverse=True)
    leaders = scored[:top_n]
    laggards = list(reversed(scored[-top_n:])) if len(scored) >= top_n else list(reversed(scored))
    # Avoid duplicating the same name in both lists when n is tiny.
    lead_tickers = {x["ticker"] for x in leaders}
    laggards = [x for x in laggards if x["ticker"] not in lead_tickers][:top_n]
    return {"leaders": leaders, "laggards": laggards, "period": period}

def _short_name(name: str, ticker: str, max_len: int = 6) -> str:
    text = (name or ticker).strip()
    # Prefer Chinese / short ticker display.
    if len(text) <= max_len:
        return text
    # Drop common suffixes
    for suf in (" Co Ltd", " Company Limited", " Group", " Inc", " Ltd"):
        if text.endswith(suf):
            text = text[: -len(suf)].strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def format_attribution_line(attr: dict) -> str:
    """One-liner: ``1M 贡献 +泡泡 +腾讯 · −理想 −小鹏``."""
    def _bits(items, sign_force=None):
        out = []
        for it in items:
            tag = _short_name(it["name"], it["ticker"])
            ret = it["ret"]
            sign = "+" if ret >= 0 else "−"
            if sign_force:
                sign = sign_force
            out.append(f"{sign}{tag}")
        return out

    leaders = _bits(attr.get("leaders") or [])
    laggards = _bits(attr.get("laggards") or [], sign_force="−")
    left = " ".join(leaders) if leaders else "—"
    right = " ".join(laggards) if laggards else "—"
    return f"1M 贡献 {left} · {right}"


def basket_breadth(basket: Basket) -> dict:
    """Share of components that look cheap vs own history / deep YTD drawdown."""
    tickers = [c.ticker for c in basket.constituents]
    fund = fundamentals_for(tickers)
    n = len(tickers)
    n_cheap = 0
    n_rich = 0
    n_deep_dd = 0
    n_valued = 0
    n_dd = 0

    for c in basket.constituents:
        pe_h = stock_pe_history(c.ticker)
        fwd = None
        trail = None
        if fund is not None and c.ticker in fund.index:
            row = fund.loc[c.ticker]
            fwd = _safe_pe(row.get("fwd_pe"))
            trail = _safe_pe(row.get("pe_ttm"))
        stats = pe_stats_vs_history(pe_h, trail, fwd)
        pctile = stats.get("fwd_vs_5y_trail_pctile")
        if pctile is None and trail is not None:
            pctile = stats.get("trail_pctile_5y")
        if pctile is not None and pd.notna(pctile):
            n_valued += 1
            if pctile < CHEAP_PCTILE:
                n_cheap += 1
            elif pctile > RICH_PCTILE:
                n_rich += 1

        px = load_price(c.ticker)
        dd = ytd_drawdown(px) if px is not None else None
        if dd is not None and pd.notna(dd):
            n_dd += 1
            if dd <= DEEP_DD:
                n_deep_dd += 1

    return {
        "n": n,
        "n_cheap": n_cheap,
        "n_rich": n_rich,
        "n_deep_dd": n_deep_dd,
        "n_valued": n_valued,
        "n_dd": n_dd,
        "pct_cheap": (n_cheap / n_valued) if n_valued else None,
        "pct_deep_dd": (n_deep_dd / n_dd) if n_dd else None,
    }


def format_breadth_line(breadth: dict) -> str:
    """One-liner: ``Breadth 4/10 偏便宜 · 3/10 深回调``."""
    n = breadth.get("n") or 0
    cheap = breadth.get("n_cheap") or 0
    deep = breadth.get("n_deep_dd") or 0
    valued = breadth.get("n_valued") or 0
    ndd = breadth.get("n_dd") or 0
    cheap_den = valued or n
    dd_den = ndd or n
    return f"Breadth {cheap}/{cheap_den} 偏便宜 · {deep}/{dd_den} 深回调"


def triage_baskets(rows: pd.DataFrame) -> dict[str, list[dict]]:
    """Simple Opportunity / Risk lists from overview valuation rows.

    Opportunity: washed out (DD ≤ −15%) and not rich (pctile < 70), or clearly cheap.
    Risk: rich (pctile > 70) and still near highs (DD > −12%) or strong YTD.
    """
    opps: list[dict] = []
    risks: list[dict] = []
    if rows is None or rows.empty:
        return {"opportunities": opps, "risks": risks}

    for _, r in rows.iterrows():
        name = r.get("Basket")
        bid = r.get("_id")
        pctile = r.get("fwd_vs_5y_trail_pctile")
        dd = r.get("DD vs YTD peak")
        ytd = r.get("YTD")
        label, key = richness_label(pctile if pd.notna(pctile) else None)

        dd_v = float(dd) if dd is not None and pd.notna(dd) else None
        ytd_v = float(ytd) if ytd is not None and pd.notna(ytd) else None
        pct_v = float(pctile) if pctile is not None and pd.notna(pctile) else None

        why_opp = None
        opp_score = None
        if dd_v is not None and dd_v <= -0.15 and (pct_v is None or pct_v < RICH_PCTILE):
            why_opp = f"已回调 {dd_v:+.0%} · {label}"
            opp_score = dd_v  # more negative first
        elif pct_v is not None and pct_v < CHEAP_PCTILE and (ytd_v is None or ytd_v < 0.15):
            why_opp = f"{label}" + (f" · YTD {ytd_v:+.0%}" if ytd_v is not None else "")
            opp_score = (pct_v - 100) / 100.0  # cheaper first

        why_risk = None
        risk_score = None
        if pct_v is not None and pct_v > RICH_PCTILE:
            near_high = dd_v is None or dd_v > -0.12
            hot_ytd = ytd_v is not None and ytd_v > 0.20
            if near_high or hot_ytd:
                bits = [label]
                if ytd_v is not None:
                    bits.append(f"YTD {ytd_v:+.0%}")
                if dd_v is not None:
                    bits.append(f"回调 {dd_v:+.0%}")
                why_risk = " · ".join(bits)
                risk_score = pct_v

        item = {"name": name, "_id": bid, "label": label}
        if why_opp:
            opps.append({**item, "why": why_opp, "_score": opp_score})
        if why_risk:
            risks.append({**item, "why": why_risk, "_score": risk_score})

    opps.sort(key=lambda x: (x.get("_score") is None, x.get("_score") if x.get("_score") is not None else 0))
    risks.sort(key=lambda x: -(x.get("_score") or 0))
    return {"opportunities": opps[:6], "risks": risks[:6]}
