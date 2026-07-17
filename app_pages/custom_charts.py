import streamlit as st

from src.chart_builder import (FREEFORM_EXAMPLE, METRICS, build_template_logic,
                               extract_logic, preview_logic)
from src.chart_registry import (chart_description, chart_title, load_chart_modules,
                                read_chart, render_chart, save_chart_logic)
from src.ui import internal_badge, internal_page

st.session_state.setdefault("chart_editor", None)  # None | "new" | slug

internal_page()
st.title("Team Charts")
st.markdown(
    "Pick a template and the metrics you care about — or write a free-form "
    "script for an adhoc chart. Data comes from the shared market-data layer "
    "(EODHD → Tushare / akshare). Preview live, then save. Imports and helpers "
    "are injected automatically."
)

modules = load_chart_modules()

if st.button("＋ Create a new chart", type="primary"):
    st.session_state.chart_editor = "new"

editor = st.session_state.chart_editor
if editor is not None:
    with st.container(border=True):
        internal_badge("Chart builder — internal only.")

        if editor == "new":
            st.markdown("##### New chart")
            template = st.radio(
                "Template",
                ["bar", "scatter", "price", "freeform"],
                format_func={
                    "bar": "Bar ranking — one bar per stock for a metric",
                    "scatter": "Scatter — compare two metrics, sized by market cap",
                    "price": "Price history — constituents rebased to 100",
                    "freeform": "Free-form script — Plotly / Streamlit / HTML",
                }.get,
                key="tpl_choice",
            )

            metric_names = list(METRICS)
            params = {}
            default_title = ""
            default_desc = ""
            logic = ""

            if template == "bar":
                metric = st.selectbox("Metric", metric_names,
                                      index=metric_names.index("YTD return %"),
                                      key="tpl_bar_metric")
                params = {"metric": metric}
                default_title = f"{metric} by stock"
                default_desc = f"One bar per constituent, ranked by {metric}, colored by basket."
                logic = build_template_logic(template, **params)
            elif template == "scatter":
                c1, c2, c3 = st.columns([2, 2, 1])
                x = c1.selectbox("X axis", metric_names,
                                 index=metric_names.index("PE (TTM)"), key="tpl_x")
                y = c2.selectbox("Y axis", metric_names,
                                 index=metric_names.index("PB"), key="tpl_y")
                log = c3.checkbox("Log scale", value=True, key="tpl_log")
                params = {"x": x, "y": y, "log": log}
                default_title = f"{x} vs {y}"
                default_desc = f"{x} vs {y} for every constituent, sized by market cap, colored by basket."
                logic = build_template_logic(template, **params)
            elif template == "price":
                default_title = "Constituent price history"
                default_desc = "All constituents rebased to 100, from the local price cache."
                logic = build_template_logic(template, **params)
            else:
                default_title = "Adhoc chart"
                default_desc = "Free-form script chart."
                st.caption(
                    "Write the render body only — imports and helpers are injected "
                    "automatically. Available: `st`, `pd`, `px`, `go`, `load_baskets`, "
                    "`fundamentals_frame`, `price_frame`, `plotly_layout`, plus "
                    "`basket` / `compact`. For raw HTML use "
                    "`st.markdown(..., unsafe_allow_html=True)` or "
                    "`st.components.v1.html(...)`. Pasting a fuller module also works."
                )
                logic = st.text_area(
                    "Script",
                    value=FREEFORM_EXAMPLE,
                    height=320,
                    key="tpl_freeform_logic",
                    help="Render body of def render(basket=None, compact=False).",
                )

            title = st.text_input("Title", value=default_title, key=f"tpl_title_{template}")
            description = st.text_input("Description", value=default_desc,
                                        key=f"tpl_desc_{template}")

            if template != "freeform":
                st.markdown("###### Preview")
                try:
                    preview_logic(logic, compact=True)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Preview failed: {exc}")

                with st.expander("Edit logic (optional)", expanded=False):
                    st.caption(
                        "Only the render body — imports and helpers are injected automatically. "
                        "Helpers: `fundamentals_frame(basket)`, `price_frame(tickers)`, "
                        "`load_baskets`, `px`, `go`, `plotly_layout`."
                    )
                    edited = st.text_area(
                        "Logic", value=logic, height=260,
                        label_visibility="collapsed",
                        key=f"tpl_logic_{template}_{sorted(params.items())!s}",
                    )
                    if edited.strip() != logic.strip():
                        logic = edited
                        st.markdown("###### Preview (edited logic)")
                        try:
                            preview_logic(logic, compact=True)
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"Preview failed: {exc}")
            else:
                st.markdown("###### Preview")
                try:
                    preview_logic(logic, compact=True)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Preview failed: {exc}")

            save_col, cancel_col = st.columns(2)
            with save_col:
                if st.button("Add to gallery", type="primary"):
                    if not title.strip():
                        st.error("Title is required.")
                    elif template == "freeform" and not logic.strip():
                        st.error("Script is required.")
                    else:
                        path = save_chart_logic(title.strip(),
                                                description.strip() or title.strip(),
                                                logic)
                        st.session_state.chart_editor = None
                        st.cache_data.clear()
                        st.toast(f"Saved {path.name}")
                        st.rerun()
            with cancel_col:
                if st.button("Cancel"):
                    st.session_state.chart_editor = None
                    st.rerun()

        else:
            existing = dict(modules).get(editor)
            st.markdown(f"##### Edit: {chart_title(existing) if existing else editor}")
            source = read_chart(editor) or ""
            title = st.text_input("Title", value=chart_title(existing) if existing else editor)
            description = st.text_input(
                "Description",
                value=chart_description(existing) if existing else "",
            )
            st.caption(
                "Render body only — imports/helpers are added on save. "
                "Helpers: `st`, `px`, `go`, `fundamentals_frame`, `price_frame`, "
                "`load_baskets`, `plotly_layout`. HTML via "
                "`st.markdown(..., unsafe_allow_html=True)` or "
                "`st.components.v1.html(...)`."
            )
            logic = st.text_area(
                "Logic (render body only)",
                value=extract_logic(source),
                height=280,
                help="Imports are added automatically on save.",
            )
            st.markdown("###### Preview")
            try:
                preview_logic(logic, compact=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Preview failed: {exc}")

            save_col, cancel_col = st.columns(2)
            with save_col:
                if st.button("Save changes", type="primary"):
                    path = save_chart_logic(title, description, logic, slug=editor)
                    st.session_state.chart_editor = None
                    st.cache_data.clear()
                    st.toast(f"Saved {path.name}")
                    st.rerun()
            with cancel_col:
                if st.button("Cancel"):
                    st.session_state.chart_editor = None
                    st.rerun()

if not modules:
    st.info("No charts yet. Click Create a new chart and pick a template.")
    st.stop()

st.subheader("Many charts")
for row in range(0, len(modules), 2):
    cols = st.columns(2)
    for col, (slug, mod) in zip(cols, modules[row:row + 2]):
        with col:
            with st.container(border=True):
                head, edit = st.columns([5, 1])
                head.markdown(f"#### {chart_title(mod)}")
                if edit.button("Edit", key=f"edit_{slug}"):
                    st.session_state.chart_editor = slug
                    st.rerun()
                desc = chart_description(mod)
                if desc:
                    st.caption(desc)
                try:
                    render_chart(mod, compact=True)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Chart failed to render: {exc}")
