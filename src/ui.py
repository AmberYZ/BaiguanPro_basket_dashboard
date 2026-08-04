"""UI helpers shared across Streamlit pages."""

from __future__ import annotations

import math
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

GREEN = "#0F8A5F"
RED = "#C0392B"
MUTED = "#6B7280"
BLUE = "#1D6FBF"
ORANGE = "#C47A2C"
PURPLE = "#7C3AED"
GRID = "rgba(28, 36, 48, 0.08)"
PAPER = "#F4F6F8"
CARD = "#FFFFFF"
INK = "#1C2430"

# Fixed period palette — same color for every ticker / basket / benchmark.
PERIOD_COLORS = {
    "YTD": BLUE,
    "3M": ORANGE,
    "1M": PURPLE,
    "5D": GREEN,
    "1Y": "#BE185D",
}


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(ellipse 70% 45% at 8% -8%, #dfece8 0%, transparent 55%),
            radial-gradient(ellipse 55% 40% at 100% 0%, #e8eef5 0%, transparent 50%),
            #F4F6F8;
          color: #1C2430;
        }
        h1, h2, h3 { letter-spacing: -0.03em; color: #1C2430; }
        div[data-testid="stMetric"] {
          background: #FFFFFF;
          border: 1px solid #D9DEE7;
          border-radius: 14px;
          padding: 14px 16px;
          box-shadow: 0 1px 2px rgba(28,36,48,0.04);
        }
        div[data-testid="stMetricValue"] {
          font-size: 1.25rem;
          font-weight: 700;
          color: #1C2430;
        }
        div[data-testid="stDataFrame"] {
          border: 1px solid #D9DEE7;
          border-radius: 14px;
          overflow: hidden;
          background: #FFFFFF;
        }
        .baiguan-card {
          background: #FFFFFF;
          border: 1px solid #D9DEE7;
          border-radius: 16px;
          padding: 16px;
          margin-bottom: 16px;
          box-shadow: 0 1px 3px rgba(28,36,48,0.05);
        }
        .baiguan-card-title {
          font-size: 1.05rem;
          font-weight: 720;
          margin-bottom: 4px;
          color: #1C2430;
        }
        .muted { color: #6B7280; }
        .up { color: #0F8A5F; font-weight: 650; }
        .down { color: #C0392B; font-weight: 650; }
        .flat { color: #6B7280; font-weight: 650; }
        .pill {
          display: inline-block;
          border: 1px solid #C5D4E8;
          background: #EEF4FB;
          color: #1D4F8C;
          padding: 4px 9px;
          border-radius: 999px;
          font-size: 0.78rem;
          margin: 2px 4px 2px 0;
        }
        .market-table-wrap {
          overflow-x: auto;
          border: 1px solid #D9DEE7;
          border-radius: 14px;
          background: #FFFFFF;
        }
        .market-table-wrap.compact table.market-table {
          font-size: 0.7rem;
          min-width: 0;
        }
        .market-table-wrap.compact .market-table th,
        .market-table-wrap.compact .market-table td {
          padding: 6px 6px;
          white-space: nowrap;
        }
        .internal-badge {
          display: inline-block;
          border: 1px solid #D1D5DB;
          background: #F3F4F6;
          color: #6B7280;
          padding: 3px 10px;
          border-radius: 6px;
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }
        .internal-note { color: #6B7280; font-size: 0.78rem; }
        .internal-heading {
          color: #6B7280 !important;
          font-size: 1.05rem;
          font-weight: 600;
          margin: 0.6rem 0 0.35rem;
        }
        .internal-page h1,
        .internal-page h2,
        .internal-page h3,
        .internal-page h4,
        .internal-page p,
        .internal-page label,
        .internal-page .stMarkdown,
        .internal-page [data-testid="stCaptionContainer"],
        .internal-page [data-testid="stWidgetLabel"] {
          color: #4B5563 !important;
        }
        .internal-page h1 { color: #1C2430 !important; }
        .tag-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 14px; }
        .admin-line { color: #6B7280; font-size: 0.74rem; margin: -6px 0 10px; }
        table.market-table {
          border-collapse: collapse;
          width: 100%;
          min-width: 760px;
          font-size: 0.86rem;
          color: #1C2430;
        }
        .market-table th {
          color: #6B7280;
          font-weight: 600;
          text-align: right;
          padding: 11px 12px;
          border-bottom: 1px solid #E5E9F0;
          white-space: nowrap;
          background: #F7F8FA;
        }
        .market-table-wrap.scroll {
          overflow-y: auto;
        }
        .market-table-wrap.scroll thead th {
          position: sticky;
          top: 0;
          background: #F7F8FA;
          z-index: 1;
        }
        .market-table td {
          padding: 11px 12px;
          text-align: right;
          border-bottom: 1px solid #EEF1F5;
          white-space: nowrap;
        }
        .market-table th:first-child, .market-table td:first-child,
        .market-table th:nth-child(2), .market-table td:nth-child(2) {
          text-align: left;
        }
        .market-table tr:last-child td { border-bottom: 0; }
        .market-table tr:hover td { background: #F3F7FC; }
        .market-table th .col-tip {
          cursor: help;
          border-bottom: 1px dotted rgba(107,114,128,0.55);
          text-decoration: none;
        }
        .market-table th .col-tip::after {
          content: attr(data-tip);
          position: absolute;
          left: 50%;
          bottom: calc(100% + 8px);
          transform: translateX(-50%);
          min-width: 12rem;
          max-width: 18rem;
          padding: 8px 10px;
          border-radius: 8px;
          background: #1C2430;
          border: 1px solid #1C2430;
          color: #F9FAFB;
          font-size: 0.72rem;
          font-weight: 500;
          line-height: 1.35;
          white-space: normal;
          text-align: left;
          box-shadow: 0 10px 24px rgba(28,36,48,0.18);
          opacity: 0;
          pointer-events: none;
          transition: opacity 0.12s ease;
          z-index: 4;
        }
        .market-table th { position: relative; }
        .market-table th .col-tip:hover::after { opacity: 1; }
        .news-feed { margin: 6px 0 0; }
        .news-item {
          display: grid;
          grid-template-columns: 4.5rem 1fr;
          gap: 10px;
          padding: 9px 0;
          border-bottom: 1px solid #EEF1F5;
          align-items: baseline;
        }
        .news-item:last-child { border-bottom: 0; }
        .news-meta { color: #6B7280; font-size: 0.72rem; line-height: 1.3; }
        .news-title {
          color: #1C2430;
          font-size: 0.86rem;
          line-height: 1.35;
          text-decoration: none;
        }
        .news-title:hover { color: #1D6FBF; }
        .news-ticker {
          color: #1D6FBF;
          font-size: 0.72rem;
          font-weight: 650;
          margin-right: 6px;
        }
        .performance-strip {
          display: grid;
          grid-template-columns: repeat(4, minmax(64px, 1fr));
          gap: 6px;
          margin: 6px 0 8px;
        }
        .performance-item {
          border-left: 2px solid #D9DEE7;
          padding-left: 8px;
        }
        .performance-label { color: #6B7280; font-size: 0.68rem; }
        .performance-value { font-size: 0.95rem; margin-top: 1px; font-weight: 650; }
        .valuation-strip {
          display: grid;
          grid-template-columns: 1fr 1fr 1fr 1.15fr 0.9fr;
          gap: 6px 10px;
          margin: 2px 0 8px;
          padding: 8px 10px;
          background: #F7F8FA;
          border: 1px solid #E5E9F0;
          border-radius: 10px;
          align-items: start;
        }
        .valuation-item .valuation-label {
          color: #6B7280;
          font-size: 0.65rem;
          letter-spacing: 0.01em;
          line-height: 1.2;
          white-space: nowrap;
        }
        .valuation-item .valuation-value {
          color: #1C2430;
          font-size: 0.92rem;
          font-weight: 700;
          margin-top: 2px;
          line-height: 1.25;
          white-space: nowrap;
        }
        .valuation-value.concl {
          font-size: 0.82rem;
          font-weight: 650;
        }
        .valuation-value.chip-cheap { color: #0F8A5F !important; }
        .valuation-value.chip-fair { color: #C47A2C !important; }
        .valuation-value.chip-rich { color: #C0392B !important; }
        .valuation-value.chip-muted { color: #6B7280 !important; }
        .valuation-value.neg { color: #C0392B !important; }
        .valuation-value.pos { color: #0F8A5F !important; }
        .triage-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          margin: 8px 0 16px;
        }
        .triage-col {
          background: #FFFFFF;
          border: 1px solid #D9DEE7;
          border-radius: 12px;
          padding: 10px 12px;
        }
        .triage-col.opp { border-left: 3px solid #0F8A5F; }
        .triage-col.risk { border-left: 3px solid #C0392B; }
        .triage-head {
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: #6B7280;
          margin-bottom: 6px;
        }
        .triage-item {
          font-size: 0.82rem;
          line-height: 1.35;
          color: #1C2430;
          margin: 4px 0;
        }
        .triage-item .why { color: #6B7280; }
        .triage-empty { color: #9CA3AF; font-size: 0.8rem; }
        .insight-line {
          color: #4B5563;
          font-size: 0.78rem;
          line-height: 1.4;
          margin: 2px 0 8px;
        }
        .metric-grid {
          display: grid;
          grid-template-columns: repeat(8, minmax(72px, 1fr));
          gap: 8px;
          margin: 6px 0 14px;
        }
        .metric-box {
          background: #FFFFFF;
          border: 1px solid #D9DEE7;
          border-radius: 10px;
          padding: 10px 10px;
        }
        .metric-label { color: #6B7280; font-size: 0.7rem; }
        .metric-value { font-size: 1.12rem; font-weight: 700; margin-top: 3px; color: #1C2430; }
        @media (max-width: 900px) {
          .metric-grid { grid-template-columns: repeat(4, 1fr); }
          .valuation-strip {
            grid-template-columns: repeat(3, 1fr);
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def plotly_layout(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        margin=dict(l=24, r=18, t=24, b=24),
        legend=dict(orientation="h", y=-0.18),
        font=dict(color=INK, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    )
    return fig


def valuation_strip(
    avg_fwd_pe: float | None,
    pe_5y_avg: float | None,
    avg_trail_pe: float | None,
    *,
    conclusion: str | None = None,
    conclusion_key: str = "muted",
    drawdown: float | None = None,
) -> None:
    """Compact valuation strip: PE levels + richness conclusion + YTD drawdown."""

    def _fmt(v: float | None, digits: int = 1) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)) or pd.isna(v):
            return "—"
        return f"{float(v):.{digits}f}"

    if drawdown is None or (isinstance(drawdown, float) and not math.isfinite(drawdown)) or pd.isna(drawdown):
        dd_txt, dd_cls = "—", "chip-muted"
    else:
        dd_txt = f"{float(drawdown):+.1%}"
        dd_cls = "neg" if drawdown < 0 else ("pos" if drawdown > 0 else "chip-muted")

    concl = escape(conclusion or "—")
    chip = {
        "cheap": "chip-cheap",
        "fair": "chip-fair",
        "rich": "chip-rich",
    }.get(conclusion_key, "chip-muted")

    st.markdown(
        f"""
        <div class="valuation-strip">
          <div class="valuation-item">
            <div class="valuation-label">Avg Fwd</div>
            <div class="valuation-value">{_fmt(avg_fwd_pe)}</div>
          </div>
          <div class="valuation-item">
            <div class="valuation-label">5y Avg</div>
            <div class="valuation-value">{_fmt(pe_5y_avg)}</div>
          </div>
          <div class="valuation-item">
            <div class="valuation-label">Trail now</div>
            <div class="valuation-value">{_fmt(avg_trail_pe)}</div>
          </div>
          <div class="valuation-item">
            <div class="valuation-label">vs 5y</div>
            <div class="valuation-value concl {chip}">{concl}</div>
          </div>
          <div class="valuation-item">
            <div class="valuation-label">已回调</div>
            <div class="valuation-value {dd_cls}">{dd_txt}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def triage_panel(opportunities: list[dict], risks: list[dict]) -> None:
    """Compact Opportunity / Risk two-column snapshot."""

    def _items(rows: list[dict]) -> str:
        if not rows:
            return '<div class="triage-empty">—</div>'
        bits = []
        for r in rows:
            name = escape(str(r.get("name") or ""))
            why = escape(str(r.get("why") or ""))
            bits.append(
                f'<div class="triage-item"><strong>{name}</strong>'
                f' <span class="why">· {why}</span></div>'
            )
        return "".join(bits)

    st.markdown(
        f"""
        <div class="triage-grid">
          <div class="triage-col opp">
            <div class="triage-head">Opportunity</div>
            {_items(opportunities)}
          </div>
          <div class="triage-col risk">
            <div class="triage-head">Risk</div>
            {_items(risks)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def insight_line(*parts: str | None) -> None:
    """One muted caption line joining non-empty insight fragments."""
    text = "  ·  ".join(p for p in parts if p)
    if not text:
        return
    st.markdown(f'<div class="insight-line">{escape(text)}</div>', unsafe_allow_html=True)


def sort_controls(
    options: list[str],
    *,
    key: str,
    default: str,
) -> tuple[str, bool]:
    """Period sort buttons; clicking the active period toggles high↔low.

    Returns ``(column, ascending)`` for pandas ``sort_values``. Charts that
    draw categories on the y-axis should put the first sorted row at the
    **top** (e.g. ``autorange="reversed"``).
    """
    state_col = f"{key}_col"
    state_asc = f"{key}_asc"
    if state_col not in st.session_state:
        st.session_state[state_col] = default
    if state_asc not in st.session_state:
        st.session_state[state_asc] = False  # high → low by default

    cols = st.columns([1.2] + [1] * len(options))
    with cols[0]:
        if st.session_state[state_asc]:
            st.caption("Sort ↑ top = low")
        else:
            st.caption("Sort ↓ top = high")
    for i, opt in enumerate(options):
        with cols[i + 1]:
            active = st.session_state[state_col] == opt
            short = opt.replace("DD vs YTD peak", "DD")
            label = f"● {short}" if active else short
            if st.button(
                label,
                key=f"{key}_btn_{opt}",
                type="primary" if active else "secondary",
                width="stretch",
            ):
                if active:
                    st.session_state[state_asc] = not st.session_state[state_asc]
                else:
                    st.session_state[state_col] = opt
                    st.session_state[state_asc] = False
                st.rerun()
    return st.session_state[state_col], st.session_state[state_asc]


def pct_color(value) -> str:
    if value is None or pd.isna(value):
        return "color: #6B7280"
    return f"color: {GREEN if value >= 0 else RED}; font-weight: 650"


def fmt_pct(value, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.{decimals}%}"


def fmt_num(value, decimals: int = 1, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, float) and math.isfinite(value):
        return f"{value:.{decimals}f}{suffix}"
    return str(value)


def metric_delta(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return "positive" if value >= 0 else "negative"


def signed_class(value) -> str:
    if value is None or pd.isna(value):
        return "flat"
    return "up" if value >= 0 else "down"


def dataframe_return_styler(df: pd.DataFrame, pct_cols: list[str]) -> pd.io.formats.style.Styler:
    styles = (
        df.style
        .map(lambda v: pct_color(v), subset=[c for c in pct_cols if c in df.columns])
        .format({c: "{:+.1%}" for c in pct_cols if c in df.columns}, na_rep="—")
    )
    return styles


def card(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="baiguan-card">
          <div class="baiguan-card-title">{title}</div>
          <div class="muted">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def market_table(
    df: pd.DataFrame,
    *,
    pct_cols: list[str] | None = None,
    formats: dict[str, str] | None = None,
    max_rows: int | None = None,
    row_height: int = 44,
    compact: bool = False,
    link_map: dict[str, dict[str, str]] | None = None,
    col_help: dict[str, str] | None = None,
) -> None:
    """Render a clearly read-only HTML market table.

    When ``max_rows`` is set and the table has more rows, the body becomes
    vertically scrollable (with a sticky header) so long holdings lists don't
    make the page grow without bound.

    ``link_map`` maps a column name to ``{cell_value: href}`` so that matching
    cells render as in-app links (e.g. basket name → Basket Detail).

    ``col_help`` maps a column name to a hover tooltip explaining the metric
    (e.g. that Sharpe / Max DD are computed since inception).
    """
    pct_cols = pct_cols or []
    formats = formats or {}
    link_map = link_map or {}
    col_help = col_help or {}
    wrap_class = "market-table-wrap"
    if compact:
        wrap_class += " compact"
        row_height = min(row_height, 32)
    style = ""
    if max_rows is not None and len(df) > max_rows:
        wrap_class += " scroll"
        # header (~44px) + max_rows visible rows before scrolling kicks in
        style = f' style="max-height: {44 + max_rows * row_height}px"'
    parts = [f'<div class="{wrap_class}"{style}><table class="market-table"><thead><tr>']
    for col in df.columns:
        tip = col_help.get(str(col))
        if tip:
            parts.append(
                f'<th><span class="col-tip" data-tip="{escape(tip)}">'
                f'{escape(str(col))}</span></th>')
        else:
            parts.append(f"<th>{escape(str(col))}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in df.iterrows():
        parts.append("<tr>")
        for col in df.columns:
            value = row[col]
            css = ""
            if col in pct_cols:
                text = fmt_pct(value)
                css = signed_class(value)
            elif value is None or pd.isna(value):
                text = "—"
                css = "flat"
            elif col in formats:
                try:
                    text = formats[col].format(value)
                except (ValueError, TypeError):
                    text = str(value)
            else:
                text = str(value)
            href = link_map.get(col, {}).get(str(value)) if value is not None else None
            if href:
                cell = (f'<a href="{escape(href)}" style="color:#5EA0FF;'
                        f'text-decoration:none;font-weight:600">{escape(text)}</a>')
            else:
                cell = escape(text)
            parts.append(f'<td class="{css}">{cell}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def news_feed(articles: list[dict], *, start: int = 0, count: int = 8) -> None:
    """Compact headline list — title + date + ticker, links open in a new tab."""
    if not articles:
        st.caption("No recent headlines found for these tickers.")
        return
    slice_ = articles[start:start + count]
    parts = ['<div class="news-feed">']
    for item in slice_:
        title = escape(str(item.get("title") or ""))
        link = str(item.get("link") or "").strip()
        date = escape(str(item.get("date") or "")[:10])
        ticker = escape(str(item.get("ticker") or ""))
        if link:
            title_html = (
                f'<a class="news-title" href="{escape(link)}" target="_blank" '
                f'rel="noopener noreferrer">{title}</a>'
            )
        else:
            title_html = f'<span class="news-title">{title}</span>'
        parts.append(
            f'<div class="news-item">'
            f'<div class="news-meta">{date}</div>'
            f'<div><span class="news-ticker">{ticker}</span>{title_html}</div>'
            f"</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def performance_strip(items: list[tuple[str, object]]) -> None:
    blocks = []
    for label, value in items:
        blocks.append(
            f'<div class="performance-item">'
            f'<div class="performance-label">{escape(label)}</div>'
            f'<div class="performance-value {signed_class(value)}">{fmt_pct(value)}</div>'
            f"</div>"
        )
    st.markdown(
        f'<div class="performance-strip">{"".join(blocks)}</div>',
        unsafe_allow_html=True,
    )


def internal_badge(note: str = "Internal — not visible in share view") -> None:
    """Muted marker for internal-only sections that never appear in share view."""
    st.markdown(
        f'<span class="internal-badge">Internal</span> '
        f'<span class="internal-note">{escape(note)}</span>',
        unsafe_allow_html=True,
    )


def internal_page() -> None:
    """Softens typography on fully-internal pages (Propose, Data & Update)."""
    st.markdown('<div class="internal-page" style="display:none"></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp .block-container h1 { color: #D1D5DB !important; }
        .stApp .block-container h2,
        .stApp .block-container h3,
        .stApp .block-container h4,
        .stApp .block-container p,
        .stApp .block-container [data-testid="stCaptionContainer"] p,
        .stApp .block-container [data-testid="stWidgetLabel"] p,
        .stApp .block-container label {
          color: #9CA3AF !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def internal_heading(text: str) -> None:
    st.markdown(f'<div class="internal-heading">{escape(text)}</div>', unsafe_allow_html=True)


def tag_filter(
    all_tags: list[str],
    *,
    key: str = "tag_filter",
    default: list[str] | None = None,
) -> list[str]:
    """Flat multi-select tag pills (no dropdown)."""
    if not all_tags:
        return []
    st.caption("Filter by tag" if default is None else "Tags")
    kwargs = {
        "selection_mode": "multi",
        "key": key,
        "label_visibility": "collapsed",
    }
    if default is not None:
        kwargs["default"] = [t for t in default if t in all_tags]
    return list(st.pills("Tags", all_tags, **kwargs) or [])


def share_button(label: str, share_url: str) -> None:
    """Open the clean share view in a new tab via a real button-styled link."""
    st.link_button(label, share_url)


def admin_line(text: str) -> None:
    st.markdown(f'<div class="admin-line">{escape(text)}</div>', unsafe_allow_html=True)


def metric_grid(items: list[tuple[str, object, str]]) -> None:
    """Render one value per metric with explicit color semantics."""
    blocks = []
    for label, value, kind in items:
        if kind == "pct":
            text, css = fmt_pct(value), signed_class(value)
        elif kind == "ratio":
            text = "—" if value is None or pd.isna(value) else f"{value:.2f}"
            css = signed_class(value)
        else:
            text, css = str(value), ""
        blocks.append(
            f'<div class="metric-box"><div class="metric-label">{escape(label)}</div>'
            f'<div class="metric-value {css}">{escape(text)}</div></div>'
        )
    st.markdown(f'<div class="metric-grid">{"".join(blocks)}</div>', unsafe_allow_html=True)
