"""Auto-wrapped team chart. Edit TITLE / DESCRIPTION / render() body only."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.baskets import load_baskets
from src.chart_builder import fundamentals_frame, price_frame
from src.data import fundamentals_for, load_price
from src.ui import plotly_layout

TITLE = "Valuation Map (PE vs PB)"
DESCRIPTION = ("Every constituent across selected baskets, PE-TTM vs PB, sized by "
               "market cap, colored by basket. Uses the cached fundamentals snapshot.")


def render(basket=None, compact=False):
    df = fundamentals_frame(basket)
    if df.empty:
        st.info("No fundamentals yet — run Data & Update first.")
        return
    plot_df = df.dropna(subset=["pe", "pb"])
    plot_df = plot_df[plot_df["pe"] > 0]
    if plot_df.empty:
        st.info("No valuation points available.")
        return
    fig = px.scatter(
        plot_df, x="pe", y="pb", color="basket", size="mkt_cap",
        hover_name="name", log_x=True, log_y=True,
        labels={"pe": "PE (TTM, log)", "pb": "PB (log)"},
    )
    plotly_layout(fig, height=340 if compact else 520)
    st.plotly_chart(fig, width="stretch")
