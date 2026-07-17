"""Load and render team-owned custom chart modules."""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path

import streamlit as st

CHARTS_DIR = Path(__file__).resolve().parent.parent / "custom_charts"


def chart_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "team-chart"


def load_chart_modules() -> list[tuple[str, object]]:
    modules = []
    for path in sorted(CHARTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"custom_charts.{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            modules.append((path.stem, mod))
        except Exception as exc:  # noqa: BLE001
            st.error(f"`{path.name}` failed to load: {exc}")
    return modules


def chart_title(module: object) -> str:
    return getattr(module, "TITLE", module.__name__.rsplit(".", 1)[-1])


def chart_description(module: object) -> str:
    return getattr(module, "DESCRIPTION", "")


def render_chart(module: object, *, basket=None, compact: bool = False) -> None:
    render = getattr(module, "render")
    signature = inspect.signature(render)
    kwargs = {}
    if "basket" in signature.parameters:
        kwargs["basket"] = basket
    if "compact" in signature.parameters:
        kwargs["compact"] = compact
    render(**kwargs)


def save_chart(title: str, code: str, slug: str | None = None) -> Path:
    CHARTS_DIR.mkdir(exist_ok=True)
    slug = slug or chart_slug(title)
    path = CHARTS_DIR / f"{slug}.py"
    path.write_text(code, encoding="utf-8")
    from src.github_sync import persist_file

    err = persist_file(path, f"chore: save chart {slug}")
    if err:
        raise RuntimeError(f"Saved locally but GitHub sync failed: {err}")
    return path


def save_chart_logic(title: str, description: str, logic: str,
                     slug: str | None = None) -> Path:
    """Save a chart from title + description + render-body logic only."""
    from src.chart_builder import wrap_module
    return save_chart(title, wrap_module(title, description, logic), slug=slug)


def read_chart(slug: str) -> str | None:
    path = CHARTS_DIR / f"{slug}.py"
    return path.read_text() if path.exists() else None
