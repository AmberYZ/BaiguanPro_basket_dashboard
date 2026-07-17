"""Load and save basket definitions (YAML files in baskets/)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

# Baskets committed to the repo — used as the seed on a fresh persistent disk.
REPO_BASKETS_DIR = Path(__file__).resolve().parent.parent / "baskets"
# BASKETS_DIR is env-configurable so web edits can persist on a mounted disk
# (e.g. Render). Falls back to the in-repo ./baskets for local dev.
BASKETS_DIR = Path(os.environ.get("BASKETS_DIR") or REPO_BASKETS_DIR)


def seed_baskets() -> None:
    """Populate a fresh persistent BASKETS_DIR from the repo's committed baskets.

    When BASKETS_DIR is overridden to a mounted disk it starts empty on first
    boot; seed it once so the dashboard is not blank. Never overwrites files, so
    teammates' web edits are always preserved after the first run.
    """
    if BASKETS_DIR == REPO_BASKETS_DIR:
        return
    BASKETS_DIR.mkdir(parents=True, exist_ok=True)
    if any(BASKETS_DIR.glob("*.yaml")):
        return
    for src_path in sorted(REPO_BASKETS_DIR.glob("*.yaml")):
        (BASKETS_DIR / src_path.name).write_text(
            src_path.read_text(encoding="utf-8"), encoding="utf-8")


@dataclass
class Constituent:
    ticker: str  # e.g. 600900.SH / 000333.SZ / 09992.HK
    name: str
    weight: float | None = 1.0  # 1 = equal-weight unit; normalized in Basket.weights
    note: str = ""

    @property
    def market(self) -> str:
        suffix = self.ticker.rsplit(".", 1)[-1].upper()
        return {"SH": "A", "SZ": "A", "BJ": "A", "HK": "HK"}.get(suffix, "?")


@dataclass
class Basket:
    id: str
    name: str
    status: str
    thesis: str
    inception: str  # YYYY-MM-DD
    constituents: list[Constituent]
    author: str = ""
    created: str = ""
    tags: list[str] = field(default_factory=list)
    benchmarks: list[str] = field(default_factory=lambda: ["CSI300"])
    newsletters: list[dict] = field(default_factory=list)
    watchpoints: list[str] = field(default_factory=list)
    team_charts: list[str] = field(default_factory=list)

    @property
    def weights(self) -> dict[str, float]:
        """Normalized portfolio weights.

        Missing weights default to 1 (equal-weight units). Any positive unit
        weights are renormalized to sum to 1.
        """
        raw = {
            c.ticker: (1.0 if c.weight is None else float(c.weight))
            for c in self.constituents
        }
        total = sum(max(v, 0.0) for v in raw.values())
        if total <= 0:
            n = len(raw)
            return {t: 1.0 / n for t in raw} if n else {}
        return {t: max(v, 0.0) / total for t, v in raw.items()}


def load_baskets(directory: Path = BASKETS_DIR) -> list[Basket]:
    baskets = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        # Drop blank rows left over from data_editor deletes (ticker: null / .nan).
        raw["constituents"] = [
            Constituent(**c) for c in _clean_constituents(raw.get("constituents"))
        ]
        known = {f for f in Basket.__dataclass_fields__}
        baskets.append(Basket(**{k: v for k, v in raw.items() if k in known}))
    order = {"active": 0, "proposed": 1, "archived": 2}
    baskets.sort(key=lambda b: (order.get(b.status, 9), b.name))
    return baskets


def _clean_constituents(raw: list[dict] | None) -> list[dict]:
    """Drop blank / NaN rows that Streamlit's data_editor leaves after deletes."""
    cleaned: list[dict] = []
    seen: set[str] = set()
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        if ticker is None or (isinstance(ticker, float) and pd.isna(ticker)):
            continue
        ticker = str(ticker).strip()
        if not ticker or ticker.lower() in {"nan", "none", "null"}:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        weight = row.get("weight", 1.0)
        if weight is None or (isinstance(weight, float) and pd.isna(weight)):
            weight = 1.0
        name = row.get("name")
        note = row.get("note", "")
        if name is None or (isinstance(name, float) and pd.isna(name)):
            name = ticker
        if note is None or (isinstance(note, float) and pd.isna(note)):
            note = ""
        cleaned.append({
            "ticker": ticker,
            "name": str(name).strip() or ticker,
            "weight": float(weight),
            "note": str(note),
        })
    return cleaned


def save_basket(data: dict, directory: Path = BASKETS_DIR, *,
                sync: bool = True, refresh_data: bool = False) -> Path:
    """Write a basket YAML locally and (when configured) commit it to GitHub."""
    if "constituents" in data:
        data = {**data, "constituents": _clean_constituents(data.get("constituents"))}
    slug = re.sub(r"[^a-z0-9]+", "-", data["id"].lower()).strip("-")
    path = directory / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    if sync:
        from src.github_sync import persist_file, report, trigger_data_update

        ok = report(persist_file(path, f"chore: save basket {slug}"))
        if ok and refresh_data:
            # Fire-and-forget: Actions will pull prices for any new tickers.
            report(trigger_data_update())
    return path


def basket_to_dict(basket: Basket) -> dict:
    return {
        "id": basket.id,
        "name": basket.name,
        "status": basket.status,
        "author": basket.author,
        "created": basket.created,
        "inception": basket.inception,
        "tags": basket.tags,
        "thesis": basket.thesis,
        "benchmarks": basket.benchmarks,
        "newsletters": basket.newsletters,
        "watchpoints": basket.watchpoints,
        "team_charts": basket.team_charts,
        "constituents": [
            {
                "ticker": c.ticker,
                "name": c.name,
                "weight": c.weight,
                "note": c.note,
            }
            for c in basket.constituents
        ],
    }


def update_basket_fields(basket_id: str, fields: dict,
                         directory: Path = BASKETS_DIR) -> Path:
    baskets = {b.id: b for b in load_baskets(directory)}
    if basket_id not in baskets:
        raise ValueError(f"Unknown basket id: {basket_id}")
    data = basket_to_dict(baskets[basket_id])
    data.update(fields)
    return save_basket(
        data, directory,
        refresh_data=("constituents" in fields),
    )


def delete_basket(basket_id: str, directory: Path = BASKETS_DIR) -> None:
    path = directory / f"{basket_id}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown basket id: {basket_id}")
    path.unlink()
    from src.github_sync import delete_remote_file, report

    report(delete_remote_file(path, f"chore: delete basket {basket_id}"))
