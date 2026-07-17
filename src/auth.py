"""Lightweight auth helpers for the internal shared-password gate.

Streamlit ``session_state`` alone is not enough: clicking a normal ``/page?...``
link (or refreshing the browser) starts a new session and would force a
password re-entry. We keep a short HMAC token in the URL query (``k=``) so
navigation and refresh stay signed-in until the shared password itself changes.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import streamlit as st

_AUTH_QUERY_KEY = "k"


def auth_token(password: str | None = None) -> str | None:
    password = password if password is not None else os.environ.get("APP_PASSWORD")
    if not password:
        return None
    return hmac.new(
        password.encode("utf-8"),
        b"baiguan-pro-index-auth",
        hashlib.sha256,
    ).hexdigest()[:24]


def is_authenticated() -> bool:
    if not os.environ.get("APP_PASSWORD"):
        return True
    return bool(st.session_state.get("authenticated"))


def remember_auth(password: str) -> None:
    """Mark this browser session as signed in and stamp the URL with the token."""
    token = auth_token(password)
    st.session_state.authenticated = True
    st.session_state.auth_token = token
    if token:
        st.query_params[_AUTH_QUERY_KEY] = token


def restore_auth_from_query(password: str) -> bool:
    """Return True if the URL already carries a valid auth token."""
    token = auth_token(password)
    got = st.query_params.get(_AUTH_QUERY_KEY)
    if token and got and hmac.compare_digest(str(got), token):
        st.session_state.authenticated = True
        st.session_state.auth_token = token
        return True
    return False


def keep_auth_in_url() -> None:
    """Re-attach the auth token if some page navigation dropped it."""
    token = st.session_state.get("auth_token") or auth_token()
    if token and st.query_params.get(_AUTH_QUERY_KEY) != token:
        st.query_params[_AUTH_QUERY_KEY] = token


def with_auth(url: str) -> str:
    """Append the auth token to an in-app link so hard navigations stay signed in."""
    token = st.session_state.get("auth_token") or auth_token()
    if not token:
        return url
    # Don't leak the session token onto public share views.
    if "share=" in url:
        return url
    sep = "&" if "?" in url else "?"
    if f"{_AUTH_QUERY_KEY}=" in url:
        return url
    return f"{url}{sep}{_AUTH_QUERY_KEY}={token}"


def flash_success(message: str) -> None:
    """Queue a success banner + toast that survives the next ``st.rerun()``."""
    st.session_state["_flash_success"] = message


def show_flash() -> None:
    msg = st.session_state.pop("_flash_success", None)
    if not msg:
        return
    st.toast(msg, icon="✅")
    st.success(msg)
