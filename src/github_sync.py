"""Persist web edits to GitHub so Streamlit Cloud stays durable.

Streamlit Community Cloud has an ephemeral filesystem. Without this module,
basket / chart edits made in the UI vanish on the next reboot or redeploy.

When ``GITHUB_TOKEN`` is set (Streamlit secrets or env), every local write is
also committed to the connected repo via the GitHub Contents API. Market-data
refresh is handled by ``.github/workflows/update-market-data.yml``; the UI can
kick it with ``trigger_data_update()``.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "AmberYZ/BaiguanPro_basket_dashboard"
WORKFLOW_FILE = "update-market-data.yml"


def enabled() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN", "").strip())


def _repo() -> str:
    return os.environ.get("GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO


def _branch() -> str:
    return os.environ.get("GITHUB_BRANCH", "main").strip() or "main"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN'].strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-05",
    }


def _rel(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"{path} is outside the repo root {REPO_ROOT}") from exc


def _get_sha(rel_path: str) -> str | None:
    url = f"https://api.github.com/repos/{_repo()}/contents/{rel_path}"
    resp = requests.get(url, headers=_headers(), params={"ref": _branch()}, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("sha")


def persist_file(path: Path, message: str) -> str | None:
    """Create or update ``path`` on GitHub. Returns an error string, or None."""
    if not enabled():
        return None
    path = Path(path)
    if not path.exists():
        return f"local file missing: {path}"
    rel = _rel(path)
    content_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "message": message,
        "content": content_b64,
        "branch": _branch(),
    }
    sha = _get_sha(rel)
    if sha:
        payload["sha"] = sha
    url = f"https://api.github.com/repos/{_repo()}/contents/{rel}"
    try:
        resp = requests.put(url, headers=_headers(), json=payload, timeout=60)
        if resp.status_code >= 400:
            return f"GitHub {resp.status_code}: {resp.text[:400]}"
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def delete_remote_file(path: Path, message: str) -> str | None:
    """Delete ``path`` on GitHub. Returns an error string, or None."""
    if not enabled():
        return None
    rel = _rel(Path(path))
    sha = _get_sha(rel)
    if not sha:
        return None  # already gone remotely
    url = f"https://api.github.com/repos/{_repo()}/contents/{rel}"
    try:
        resp = requests.delete(
            url,
            headers=_headers(),
            json={"message": message, "sha": sha, "branch": _branch()},
            timeout=60,
        )
        if resp.status_code >= 400:
            return f"GitHub {resp.status_code}: {resp.text[:400]}"
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
        resp = requests.post(
            url,
            headers=_headers(),
            json={"ref": _branch()},
            timeout=30,
        )
        # 204 No Content = accepted
        if resp.status_code not in (204, 201):
            return f"GitHub {resp.status_code}: {resp.text[:400]}"
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None
