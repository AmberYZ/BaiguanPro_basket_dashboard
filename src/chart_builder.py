"""Team-chart builder.

Templates and free-form scripts produce only the *logic* body of ``render()`` —
imports and helpers are injected automatically at save time.
"""

from __future__ import annotations

import json
import os
import re
from textwrap import dedent, indent

import requests

PREAMBLE = '''\
"""Auto-wrapped team chart. Edit TITLE / DESCRIPTION / render() body only."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.baskets import load_baskets
from src.chart_builder import fundamentals_frame, price_frame
from src.data import fundamentals_for, load_price
from src.ui import plotly_layout

TITLE = {title!r}
DESCRIPTION = {description!r}


def render(basket=None, compact=False):
'''

LLM_SYSTEM = """\
You write ONLY the indented body of a Python function:

    def render(basket=None, compact=False):

Do NOT write imports, the def line, TITLE, or DESCRIPTION.
Available names (already imported): st, pd, px, go, load_baskets,
fundamentals_for, load_price, fundamentals_frame, price_frame, plotly_layout.

Helpers:
- fundamentals_frame(basket=None) -> DataFrame with columns
  ticker, name, basket, pe, pb, fwd_pe, peg, eps_growth, ev_ebitda, rsi, mkt_cap,
  pct_1m, pct_3m, pct_ytd, price
- price_frame(tickers) -> DataFrame of close prices (wide, date index)
- If basket is not None, focus on that basket; else use all baskets.

Prefer Plotly via px/go, then st.plotly_chart(fig, width="stretch").
Call plotly_layout(fig, height=340 if compact else 520) before plotting.
Keep the body under ~40 lines. Use cached fundamentals / prices; do not call
external HTTP APIs yourself.
"""


def fundamentals_frame(basket=None) -> "pd.DataFrame":
    """Flat fundamentals table for one basket or every basket."""
    import pandas as pd
    from src.baskets import load_baskets
    from src.data import fundamentals_for

    baskets = [basket] if basket is not None else load_baskets()
    rows = []
    for b in baskets:
        fund = fundamentals_for([c.ticker for c in b.constituents])
        if fund is None:
            continue
        for c in b.constituents:
            if c.ticker not in fund.index:
                continue
            f = fund.loc[c.ticker]
            rows.append({
                "ticker": c.ticker,
                "name": c.name,
                "basket": b.name,
                "pe": f.get("pe_ttm"),
                "pb": f.get("pb"),
                "fwd_pe": f.get("fwd_pe"),
                "peg": f.get("peg"),
                "eps_growth": f.get("eps_growth"),
                "ev_ebitda": f.get("ev_ebitda"),
                "rsi": f.get("rsi_14"),
                "mkt_cap": f.get("mkt_cap"),
                "pct_1m": f.get("pct_1m"),
                "pct_3m": f.get("pct_3m"),
                "pct_ytd": f.get("pct_ytd"),
                "price": f.get("price"),
            })
    return pd.DataFrame(rows)


def price_frame(tickers: list[str]) -> "pd.DataFrame":
    """Wide close-price frame for the given tickers."""
    import pandas as pd
    from src.data import load_price

    series = {}
    for t in tickers:
        s = load_price(t)
        if s is not None and not s.empty:
            series[t] = s
    return pd.DataFrame(series).sort_index().ffill()


def extract_logic(source: str) -> str:
    """Pull the body of ``render`` from a full chart module."""
    match = re.search(r"def render\s*\([^)]*\):\n(.*)", source, re.DOTALL)
    if not match:
        return source.strip() + "\n"
    body = match.group(1)
    # Stop at next top-level def/class if any
    stop = re.search(r"\n(?=\S)", "\n" + body)
    lines = body.splitlines()
    # Dedent common leading whitespace
    cleaned = []
    for line in lines:
        if re.match(r"^(def |class |TITLE |DESCRIPTION )", line):
            break
        cleaned.append(line)
    text = "\n".join(cleaned).rstrip() + "\n"
    return dedent(text)


def normalize_logic(logic: str) -> str:
    """Return a render-body string.

    Accepts either a bare render body or a fuller pasted module (TITLE /
    ``def render`` / imports). Fuller modules are reduced to the render body
    so the shared preamble can still inject helpers on save/preview.
    """
    text = dedent(logic or "").strip("\n") + "\n"
    if re.search(r"(?m)^(def render\s*\(|TITLE\s*=|DESCRIPTION\s*=)", text):
        text = extract_logic(text)
    text = re.sub(r"^def render\s*\([^)]*\):\s*\n", "", text)
    return dedent(text).strip("\n") + "\n"


def wrap_module(title: str, description: str, logic: str) -> str:
    """Inject preamble + wrap user logic into a saveable chart module."""
    body = normalize_logic(logic)
    return PREAMBLE.format(title=title, description=description) + indent(body, "    ")


# ------------------------------------------------------- Template builders

# Metric label -> fundamentals_frame column. Drives the template pickers.
METRICS = {
    "YTD return %": "pct_ytd",
    "3M return %": "pct_3m",
    "1M return %": "pct_1m",
    "PE (TTM)": "pe",
    "Fwd PE": "fwd_pe",
    "PEG": "peg",
    "EPS growth (1Y)": "eps_growth",
    "PB": "pb",
    "EV/EBITDA": "ev_ebitda",
    "RSI (14)": "rsi",
    "Market cap": "mkt_cap",
    "Price": "price",
}

TEMPLATES = {
    "bar": "Bar ranking — one bar per stock for a chosen metric",
    "scatter": "Scatter — compare two metrics, sized by market cap",
    "price": "Price history — constituents rebased to 100",
    "freeform": "Free-form script — write any Plotly / Streamlit / HTML render body",
}

FREEFORM_EXAMPLE = dedent("""\
    # Helpers already available: st, pd, px, go, load_baskets,
    # fundamentals_frame, price_frame, plotly_layout, basket, compact.
    #
    # Plotly / Streamlit:
    df = fundamentals_frame(basket)
    if df.empty:
        st.info("No fundamentals yet — run Data & Update first.")
        return
    fig = px.histogram(
        df.dropna(subset=["pe"]), x="pe", color="basket", nbins=20,
        labels={"pe": "PE (TTM)"},
    )
    plotly_layout(fig, height=340 if compact else 520)
    st.plotly_chart(fig, width="stretch")

    # Raw HTML (pick one):
    # st.markdown("<div style='padding:8px'>Hello</div>", unsafe_allow_html=True)
    # st.components.v1.html("<h3>Custom HTML</h3>", height=120)
""")


def build_bar_logic(metric_label: str) -> str:
    col = METRICS[metric_label]
    logic = dedent(f"""\
        df = fundamentals_frame(basket)
        if df.empty:
            st.info("No fundamentals yet — run Data & Update first.")
            return
        plot_df = df.dropna(subset=["{col}"]).sort_values("{col}")
        if plot_df.empty:
            st.info("No data for {metric_label} in the snapshot.")
            return
        fig = px.bar(
            plot_df, x="{col}", y="name", color="basket", orientation="h",
            labels={{"{col}": "{metric_label}", "name": ""}},
        )
    """)
    if col == "rsi":
        logic += ('fig.add_vline(x=30, line_dash="dot")\n'
                  'fig.add_vline(x=70, line_dash="dot")\n')
    logic += ('plotly_layout(fig, height=340 if compact else 520)\n'
              'st.plotly_chart(fig, width="stretch")\n')
    return logic


def build_scatter_logic(x_label: str, y_label: str, *, log: bool = False) -> str:
    x_col, y_col = METRICS[x_label], METRICS[y_label]
    log_args = "log_x=True, log_y=True,\n            " if log else ""
    return dedent(f"""\
        df = fundamentals_frame(basket)
        if df.empty:
            st.info("No fundamentals yet — run Data & Update first.")
            return
        plot_df = df.dropna(subset=["{x_col}", "{y_col}"])
        if plot_df.empty:
            st.info("No data points with both {x_label} and {y_label}.")
            return
        fig = px.scatter(
            plot_df, x="{x_col}", y="{y_col}", color="basket", size="mkt_cap",
            hover_name="name", {log_args}labels={{"{x_col}": "{x_label}", "{y_col}": "{y_label}"}},
        )
        plotly_layout(fig, height=340 if compact else 520)
        st.plotly_chart(fig, width="stretch")
    """)


def build_price_logic() -> str:
    return dedent("""\
        baskets = [basket] if basket is not None else load_baskets()
        names = {}
        for b in baskets:
            for c in b.constituents:
                names[c.ticker] = c.name
        prices = price_frame(list(names))
        if prices.empty:
            st.info("No cached prices yet — run Data & Update first.")
            return
        rebased = (prices / prices.iloc[0] * 100).rename(columns=names)
        fig = px.line(rebased, labels={"value": "Rebased to 100", "index": "", "variable": ""})
        plotly_layout(fig, height=340 if compact else 520)
        st.plotly_chart(fig, width="stretch")
    """)


def build_freeform_logic() -> str:
    """Starter body for the free-form script template."""
    return FREEFORM_EXAMPLE


def build_template_logic(template: str, **params) -> str:
    """Deterministic logic from a template id + metric params."""
    if template == "bar":
        return build_bar_logic(params["metric"])
    if template == "scatter":
        return build_scatter_logic(params["x"], params["y"], log=params.get("log", False))
    if template == "price":
        return build_price_logic()
    if template == "freeform":
        return build_freeform_logic()
    raise ValueError(f"Unknown template: {template}")


def _llm_generate(prompt: str, title: str) -> str | None:
    """Optional OpenAI-compatible generation via OPENAI_API_KEY / AI_GATEWAY_API_KEY."""
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_GATEWAY_API_KEY") or ""
    if not api_key:
        return None
    base = (os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("AI_GATEWAY_BASE_URL")
            or "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("AI_GATEWAY_MODEL") or "gpt-4o-mini"
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content":
                     f"Chart title: {title}\nUser request:\n{prompt}\n\n"
                     "Return only the function body."},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:python)?\n|\n```$", "", content.strip())
        # Strip accidental def render line
        content = re.sub(r"^def render\s*\([^)]*\):\s*\n", "", content)
        return dedent(content).strip() + "\n"
    except Exception:  # noqa: BLE001
        return None


def _recipe_generate(prompt: str) -> str:
    """Deterministic fallback when no LLM key is configured."""
    p = prompt.lower()
    if any(k in p for k in ("rsi",)):
        return dedent("""\
            df = fundamentals_frame(basket)
            if df.empty:
                st.info("No fundamentals yet — run Data & Update first.")
                return
            plot_df = df.dropna(subset=["rsi"]).sort_values("rsi")
            fig = px.bar(
                plot_df, x="rsi", y="name", color="basket", orientation="h",
                labels={"rsi": "RSI (14)", "name": ""},
            )
            fig.add_vline(x=30, line_dash="dot")
            fig.add_vline(x=70, line_dash="dot")
            plotly_layout(fig, height=340 if compact else 520)
            st.plotly_chart(fig, width="stretch")
        """)
    if any(k in p for k in ("return", "performance", "涨跌", "ytd", "1m", "3m")):
        metric = "pct_ytd"
        label = "YTD %"
        if "3m" in p or "3个月" in p:
            metric, label = "pct_3m", "3M %"
        elif "1m" in p or "1个月" in p:
            metric, label = "pct_1m", "1M %"
        return dedent(f"""\
            df = fundamentals_frame(basket)
            if df.empty:
                st.info("No fundamentals yet — run Data & Update first.")
                return
            plot_df = df.dropna(subset=["{metric}"]).sort_values("{metric}")
            if plot_df.empty:
                st.info("No return data in the fundamentals snapshot.")
                return
            fig = px.bar(
                plot_df, x="{metric}", y="name", color="basket", orientation="h",
                labels={{"{metric}": "{label}", "name": ""}},
            )
            plotly_layout(fig, height=340 if compact else 520)
            st.plotly_chart(fig, width="stretch")
        """)
    # Default: valuation scatter PE vs PB (or Fwd PE if asked)
    x_col, x_label = "pe", "PE (TTM)"
    if "fwd" in p:
        x_col, x_label = "fwd_pe", "Fwd PE"
    if "peg" in p and "pb" not in p:
        return dedent("""\
            df = fundamentals_frame(basket)
            if df.empty:
                st.info("No fundamentals yet — run Data & Update first.")
                return
            plot_df = df.dropna(subset=["peg", "fwd_pe"])
            fig = px.scatter(
                plot_df, x="fwd_pe", y="peg", color="basket",
                hover_name="name",
                labels={"fwd_pe": "Fwd PE", "peg": "PEG"},
            )
            plotly_layout(fig, height=340 if compact else 520)
            st.plotly_chart(fig, width="stretch")
        """)
    return dedent(f"""\
        df = fundamentals_frame(basket)
        if df.empty:
            st.info("No fundamentals yet — run Data & Update first.")
            return
        plot_df = df.dropna(subset=["{x_col}", "pb"])
        plot_df = plot_df[plot_df["{x_col}"] > 0]
        if plot_df.empty:
            st.info("No valuation points available.")
            return
        fig = px.scatter(
            plot_df, x="{x_col}", y="pb", color="basket", size="mkt_cap",
            hover_name="name", log_x=True, log_y=True,
            labels={{"{x_col}": "{x_label}", "pb": "PB"}},
        )
        plotly_layout(fig, height=340 if compact else 520)
        st.plotly_chart(fig, width="stretch")
    """)


def generate_logic(prompt: str, title: str = "Team Chart") -> tuple[str, str]:
    """Return (logic, source) where source is 'llm' or 'recipe'."""
    logic = _llm_generate(prompt, title)
    if logic:
        return logic, "llm"
    return _recipe_generate(prompt), "recipe"


def preview_logic(logic: str, *, basket=None, compact: bool = True) -> None:
    """Execute logic in a sandboxed render context for live preview."""
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st

    from src.baskets import load_baskets
    from src.data import fundamentals_for, load_price
    from src.ui import plotly_layout

    ns = {
        "st": st,
        "pd": pd,
        "px": px,
        "go": go,
        "load_baskets": load_baskets,
        "fundamentals_for": fundamentals_for,
        "load_price": load_price,
        "fundamentals_frame": fundamentals_frame,
        "price_frame": price_frame,
        "plotly_layout": plotly_layout,
        "basket": basket,
        "compact": compact,
        "DESCRIPTION": "",
    }
    body = normalize_logic(logic).rstrip("\n")
    code = "def __preview(basket=None, compact=False):\n" + indent(body + "\n", "    ")
    exec(code, ns, ns)  # noqa: S102 - intentional preview of team chart logic
    ns["__preview"](basket=basket, compact=compact)
