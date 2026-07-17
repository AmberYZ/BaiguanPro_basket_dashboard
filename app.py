"""Baiguan Pro Index - internal basket tracking dashboard.

Run: .venv/bin/streamlit run app.py
"""

import os
import runpy
from pathlib import Path

import streamlit as st

from src.baskets import seed_baskets
from src.scheduler import start_daily_update
from src.ui import apply_theme

st.set_page_config(
    page_title="Baiguan Pro Index",
    page_icon="BP",
    layout="wide",
)
apply_theme()


@st.cache_resource
def _bootstrap() -> bool:
    """Run once per server process: seed baskets on a fresh disk and start the
    daily data refresh at 16:00 UTC (00:00 Asia/Shanghai)."""
    seed_baskets()
    start_daily_update(hour_utc=16)
    return True


_bootstrap()

if st.query_params.get("share"):
    runpy.run_path(str(Path(__file__).parent / "app_pages" / "share.py"))
    st.stop()


def password_gate() -> None:
    """Tiny internal gate for early team prototypes.

    Set APP_PASSWORD in the deployment environment to enable it. This is not a
    replacement for proper user auth when the dashboard becomes subscriber-facing.
    """
    password = os.environ.get("APP_PASSWORD")
    if not password or st.session_state.get("authenticated"):
        return
    st.title("Baiguan Pro Index")
    entered = st.text_input("Team password", type="password")
    if entered == password:
        st.session_state.authenticated = True
        st.rerun()
    if entered:
        st.error("Wrong password.")
    st.stop()


password_gate()

pages = st.navigation([
    st.Page("app_pages/overview.py", title="Overview", default=True),
    st.Page("app_pages/basket_detail.py", title="Basket Detail"),
    st.Page("app_pages/propose.py", title="Propose a Basket", icon="🔒"),
    st.Page("app_pages/custom_charts.py", title="Team Charts", icon="🔒"),
    st.Page("app_pages/data_admin.py", title="Data & Update", icon="🔒"),
])
pages.run()
