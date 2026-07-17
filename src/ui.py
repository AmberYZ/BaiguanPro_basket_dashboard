"""UI helpers shared across Streamlit pages."""

from __future__ import annotations

import math
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

GREEN = "#20C997"
RED = "#FF5C77"
MUTED = "#9CA3AF"
BLUE = "#5EA0FF"
ORANGE = "#F59E0B"
GRID = "rgba(148, 163, 184, 0.16)"
PAPER = "#080B12"
CARD = "#111827"


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(circle at top left, rgba(37, 99, 235, 0.14), transparent 34rem),
            radial-gradient(circle at top right, rgba(20, 184, 166, 0.10), transparent 30rem),
            #080B12;
        }
        h1, h2, h3 { letter-spacing: -0.03em; }
        div[data-testid="stMetric"] {
          background: linear-gradient(180deg, rgba(17,24,39,0.96), rgba(12,18,31,0.96));
          border: 1px solid rgba(148,163,184,0.16);
          border-radius: 14px;
          padding: 14px 16px;
          box-shadow: 0 10px 28px rgba(0,0,0,0.22);
        }
        div[data-testid="stMetricValue"] {
          font-size: 1.25rem;
          font-weight: 700;
        }
        div[data-testid="stDataFrame"] {
          border: 1px solid rgba(148,163,184,0.16);
          border-radius: 14px;
          overflow: hidden;
        }
        .baiguan-card {
          background: linear-gradient(180deg, rgba(17,24,39,0.98), rgba(9,13,23,0.98));
          border: 1px solid rgba(148,163,184,0.16);
          border-radius: 16px;
          padding: 16px;
          margin-bottom: 16px;
          box-shadow: 0 12px 32px rgba(0,0,0,0.24);
        }
        .baiguan-card-title {
          font-size: 1.05rem;
          font-weight: 720;
          margin-bottom: 4px;
        }
        .muted { color: #9CA3AF; }
        .up { color: #20C997; font-weight: 650; }
        .down { color: #FF5C77; font-weight: 650; }
        .flat { color: #9CA3AF; font-weight: 650; }
        .pill {
          display: inline-block;
          border: 1px solid rgba(94,160,255,0.38);
          background: rgba(94,160,255,0.12);
          color: #BFDBFE;
          padding: 4px 9px;
          border-radius: 999px;
          font-size: 0.78rem;
          margin: 2px 4px 2px 0;
        }
        .market-table-wrap {
          overflow-x: auto;
          border: 1px solid rgba(148,163,184,0.16);
          border-radius: 14px;
          background: rgba(9,13,23,0.76);
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
          border: 1px solid rgba(107,114,128,0.45);
          background: rgba(107,114,128,0.12);
          color: #9CA3AF;
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
        /* Fully-internal pages: soften default copy so it reads as backstage */
        .internal-page h1,
        .internal-page h2,
        .internal-page h3,
        .internal-page h4,
        .internal-page p,
        .internal-page label,
        .internal-page .stMarkdown,
        .internal-page [data-testid="stCaptionContainer"],
        .internal-page [data-testid="stWidgetLabel"] {
          color: #9CA3AF !important;
        }
        .internal-page h1 { color: #D1D5DB !important; }
        .tag-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 14px; }
        .admin-line { color: #6B7280; font-size: 0.74rem; margin: -6px 0 10px; }
        table.market-table {
          border-collapse: collapse;
          width: 100%;
          min-width: 760px;
          font-size: 0.86rem;
        }
        .market-table th {
          color: #9CA3AF;
          font-weight: 560;
          text-align: right;
          padding: 11px 12px;
          border-bottom: 1px solid rgba(148,163,184,0.18);
          white-space: nowrap;
        }
        .market-table-wrap.scroll {
          overflow-y: auto;
        }
        .market-table-wrap.scroll thead th {
          position: sticky;
          top: 0;
          background: #0c1220;
          z-index: 1;
        }
        .market-table td {
          padding: 11px 12px;
          text-align: right;
          border-bottom: 1px solid rgba(148,163,184,0.10);
          white-space: nowrap;
        }
        .market-table th:first-child, .market-table td:first-child,
        .market-table th:nth-child(2), .market-table td:nth-child(2) {
          text-align: left;
        }
        .market-table tr:last-child td { border-bottom: 0; }
        .market-table tr:hover td { background: rgba(94,160,255,0.055); }
        .performance-strip {
          display: grid;
          grid-template-columns: repeat(4, minmax(75px, 1fr));
          gap: 8px;
          margin: 8px 0 12px;
        }
        .performance-item {
          border-left: 2px solid rgba(148,163,184,0.22);
          padding-left: 9px;
        }
        .performance-label { color: #9CA3AF; font-size: 0.72rem; }
        .performance-value { font-size: 1.03rem; margin-top: 2px; }
        .metric-grid {
          display: grid;
          grid-template-columns: repeat(8, minmax(82px, 1fr));
          gap: 9px;
          margin: 8px 0 18px;
        }
        .metric-box {
          background: linear-gradient(180deg, rgba(17,24,39,0.98), rgba(9,13,23,0.98));
          border: 1px solid rgba(148,163,184,0.16);
          border-radius: 12px;
          padding: 13px 12px;
        }
        .metric-label { color: #9CA3AF; font-size: 0.76rem; }
        .metric-value { font-size: 1.28rem; font-weight: 730; margin-top: 5px; }
        @media (max-width: 900px) {
          .metric-grid { grid-template-columns: repeat(4, 1fr); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def plotly_layout(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        margin=dict(l=24, r=18, t=24, b=24),
        legend=dict(orientation="h", y=-0.18),
        font=dict(color="#E5E7EB"),
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    )
    return fig


def pct_color(value) -> str:
    if value is None or pd.isna(value):
        return "color: #9CA3AF"
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
                f'<th title="{escape(tip)}" style="cursor:help;'
                f'text-decoration:underline dotted rgba(156,163,175,0.6);'
                f'text-underline-offset:3px">{escape(str(col))}</th>')
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
    """Softens typography on fully-internal pages (Propose, Data, Team Charts)."""
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
