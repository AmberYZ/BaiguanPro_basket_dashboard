"""Auto-wrapped team chart. Edit TITLE / DESCRIPTION / render() body only."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.baskets import load_baskets
from src.chart_builder import fundamentals_frame, price_frame
from src.data import fundamentals_for, load_price
from src.ui import plotly_layout

TITLE = 'Avg Fwd PE & PEG by basket'
DESCRIPTION = 'Free-form script chart.'


def render(basket=None, compact=False):
    df = fundamentals_frame()  # all baskets
    if df.empty:
        st.info("No fundamentals yet — run Data & Update first.")
        return

    agg = (
        df.groupby("basket", as_index=False)
        .agg(avg_fwd_pe=("fwd_pe", "mean"), avg_peg=("peg", "mean"))
        .sort_values("avg_fwd_pe")
    )
    if agg.dropna(how="all", subset=["avg_fwd_pe", "avg_peg"]).empty:
        st.info("No Fwd PE / PEG in the snapshot.")
        return

    long = agg.melt(
        id_vars="basket",
        value_vars=["avg_fwd_pe", "avg_peg"],
        var_name="metric",
        value_name="value",
    )
    long["metric"] = long["metric"].map({
        "avg_fwd_pe": "Avg Fwd PE",
        "avg_peg": "Avg PEG",
    })

    fig = px.bar(
        long, x="value", y="basket", color="metric", orientation="h", barmode="group",
        labels={"value": "", "basket": "", "metric": ""},
    )
    plotly_layout(fig, height=340 if compact else 480)
    st.plotly_chart(fig, width="stretch")
