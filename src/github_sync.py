"""Persist web edits to GitHub so Streamlit Cloud stays durable.

Streamlit Community Cloud has an ephemeral filesystem. Without this module,
basket / chart edits made in the UI vanish on the next reboot or redeploy.

When ``GITHUB_TOKEN`` is set (Streamlit secrets or env), every local write is
also committed to the connected repo via the GitHub Contents API. Market-data
refresh is handled by ``.github/workflows/update-market-data.yml``; the UI can
kick it with ``trigger_data_update()``.

All functions here are *non-raising*: they return an error string (or ``None``
on success) so a sync problem never crashes the dashboard.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "AmberYZ/BaiguanPro_basket_dashboard"
WORKFLOW_FILE = "update-market-data.yml"


def _token() -> str:
    # split()/join() drops any stray whitespace or newlines that sneak in when a
    # token is pasted into Streamlit secrets (a common cause of malformed auth
    # headers → GitHub 400/401).
    return "".join(os.environ.get("GITHUB_TOKEN", "").split())


def enabled() -> bool:
    return bool(_token())


def _repo() -> str:
    return (os.environ.get("GITHUB_REPO", "").strip() or DEFAULT_REPO)


def _branch() -> str:
    return (os.environ.get("GITHUB_BRANCH", "").strip() or "main")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-05",
    }


def _rel(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"{path} is outside the repo root {REPO_ROOT}") from exc


def _explain(resp: requests.Response) -> str:
    """Turn a failed GitHub response into a short, actionable message."""
    try:
        msg = resp.json().get("message", "")
    except Exception:  # noqa: BLE001
        msg = (resp.text or "")[:200]
    code = resp.status_code
    hints = {
        400: "malformed request — re-paste GITHUB_TOKEN (no spaces/quotes/newlines).",
        401: "bad credentials — the token is wrong or expired.",
        403: "token lacks permission — grant Contents: Read and write (+ Actions: Read and write).",
        404: "repo/branch not found or token can't see it — check GITHUB_REPO / repository access.",
        422: "unprocessable — usually a stale file version; try again.",
    }
    hint = hints.get(code, "")
    return f"GitHub {code}: {msg} {hint}".strip()


def _get_sha(rel_path: str) -> tuple[str | None, str | None]:
    """Return (sha, error). sha is None when the file doesn't exist yet."""
    url = f"https://api.github.com/repos/{_repo()}/contents/{rel_path}"
    try:
        resp = requests.get(url, headers=_headers(),
                            params={"ref": _branch()}, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if resp.status_code == 404:
        return None, None
    if resp.status_code >= 400:
        return None, _explain(resp)
    try:
        return resp.json().get("sha"), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def persist_file(path: Path, message: str) -> str | None:
    """Create or update ``path`` on GitHub. Returns an error string, or None."""
    if not enabled():
        return None
    path = Path(path)
    if not path.exists():
        return f"local file missing: {path}"
    rel = _rel(path)
    sha, err = _get_sha(rel)
    if err:
        return err
    try:
        content_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {"message": message, "content": content_b64, "branch": _branch()}
        if sha:
            payload["sha"] = sha
        url = f"https://api.github.com/repos/{_repo()}/contents/{rel}"
        resp = requests.put(url, headers=_headers(), json=payload, timeout=60)
        if resp.status_code >= 400:
            return _explain(resp)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def delete_remote_file(path: Path, message: str) -> str | None:
    """Delete ``path`` on GitHub. Returns an error string, or None."""
    if not enabled():
        return None
    rel = _rel(Path(path))
    sha, err = _get_sha(rel)
    if err:
        return err
    if not sha:
        return None  # already gone remotely
    try:
        url = f"https://api.github.com/repos/{_repo()}/contents/{rel}"
        resp = requests.delete(
            url, headers=_headers(),
            json={"message": message, "sha": sha, "branch": _branch()}, timeout=60)
        if resp.status_code >= 400:
            return _explain(resp)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def trigger_data_update() -> str | None:
    """Fire the market-data GitHub Actions workflow. Returns error or None."""
    if not enabled():
        return "GITHUB_TOKEN not set — cannot trigger the data update workflow."
    url = (f"https://api.github.com/repos/{_repo()}/actions/workflows/"
           f"{WORKFLOW_FILE}/dispatches")
    try:
        resp = requests.post(url, headers=_headers(),
                             json={"ref": _branch()}, timeout=30)
        if resp.status_code not in (201, 204):
            return _explain(resp)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def check_connection() -> str | None:
    """Quick token/repo sanity check for the UI. Returns error or None."""
    if not enabled():
        return "GITHUB_TOKEN not set in Streamlit secrets."
    url = f"https://api.github.com/repos/{_repo()}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        if resp.status_code >= 400:
            return _explain(resp)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def report(err: str | None) -> bool:
    """Surface a sync error in the UI without crashing. True if all good."""
    if not err:
        return True
    try:
        import streamlit as st

        st.warning(
            "⚠️ Saved to this session, but **GitHub sync failed** — the change "
            "won't survive a cloud restart until this is fixed.\n\n"
            f"Details: {err}"
        )
    except Exception:  # noqa: BLE001
        print(f"[github_sync] {err}")
    return False
