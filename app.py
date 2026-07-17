"""Baiguan Pro Index - internal basket tracking dashboard.

Run: .venv/bin/streamlit run app.py
"""

import os
import runpy
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Baiguan Pro Index",
    page_icon="BP",
    layout="wide",
)


def _load_secrets_into_env() -> None:
    """Copy Streamlit Cloud secrets into os.environ for the rest of the app.

    Locally you can keep using a `.env` file (loaded by ``src.data``). On
    Streamlit Community Cloud, put the same keys in App settings → Secrets.
    """
    try:
        secrets = st.secrets
    except Exception:  # noqa: BLE001 — no secrets.toml / not configured
        return
    for key in secrets:
        try:
            value = secrets[key]
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, (str, int, float, bool)):
            os.environ.setdefault(str(key), str(value))


_load_secrets_into_env()

from src.auth import (  # noqa: E402
    keep_auth_in_url,
    remember_auth,
    restore_auth_from_query,
    show_flash,
)
from src.baskets import seed_baskets  # noqa: E402
from src.scheduler import start_daily_update  # noqa: E402
from src.ui import apply_theme  # noqa: E402

apply_theme()


@st.cache_resource
def _bootstrap() -> bool:
    """One-time process setup.

    Free Streamlit Cloud path: market data is refreshed by GitHub Actions and
    committed to the repo — do **not** start the in-process daily scheduler
    (the Cloud filesystem is ephemeral anyway).

    Paid / self-hosted path with a persistent disk: set
    ``ENABLE_INPROCESS_SCHEDULER=1`` to refresh on Beijing midnight inside
    this process.
    """
    seed_baskets()
    flag = os.environ.get("ENABLE_INPROCESS_SCHEDULER", "").strip().lower()
    if flag in ("1", "true", "yes"):
        start_daily_update(hour_utc=16)
    return True


_bootstrap()

if st.query_params.get("share"):
    runpy.run_path(str(Path(__file__).parent / "app_pages" / "share.py"))
    st.stop()


def password_gate() -> None:
    """Tiny internal gate for early team prototypes.

    Set APP_PASSWORD in Streamlit secrets (or the environment) to enable it.
    After a successful login we stamp a short token into the URL (``k=``) so
    clicking Overview → Basket Detail links, or refreshing the page, does not
    ask for the password again.
    """
    password = os.environ.get("APP_PASSWORD")
    if not password:
        return
    if st.session_state.get("authenticated"):
        keep_auth_in_url()
        return
    if restore_auth_from_query(password):
        return

    st.title("Baiguan Pro Index")
    st.caption("Enter the team password once — you'll stay signed in on this browser.")
    entered = st.text_input("Team password", type="password")
    if entered == password:
        remember_auth(password)
        st.rerun()
    if entered:
        st.error("Wrong password.")
    st.stop()


password_gate()
show_flash()

pages = st.navigation([
    st.Page("app_pages/overview.py", title="Overview", default=True),
    st.Page("app_pages/basket_detail.py", title="Basket Detail"),
    st.Page("app_pages/propose.py", title="Propose a Basket", icon="🔒"),
    st.Page("app_pages/custom_charts.py", title="Team Charts", icon="🔒"),
    st.Page("app_pages/data_admin.py", title="Data & Update", icon="🔒"),
])
pages.run()
