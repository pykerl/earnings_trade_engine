"""Theme clustering: curated ticker -> theme mapping (plan_reddit_growth §3.B1)."""

from __future__ import annotations

import logging

import pandas as pd
import yaml

from common import config

log = logging.getLogger("ete.themes")

THEMES_YAML = config.REPO_ROOT / "config" / "themes.yaml"


def load_theme_map(path=THEMES_YAML) -> dict[str, dict]:
    return yaml.safe_load(path.read_text())["themes"]


def ticker_to_theme(theme_map: dict[str, dict] | None = None) -> dict[str, str]:
    theme_map = theme_map or load_theme_map()
    out: dict[str, str] = {}
    for theme, spec in theme_map.items():
        for t in spec["tickers"]:
            if t in out:
                log.warning("ticker %s mapped to both %s and %s; keeping %s",
                            t, out[t], theme, out[t])
                continue
            out[t] = theme
    return out


def classify(tickers: pd.Series, theme_map: dict[str, dict] | None = None) -> pd.Series:
    """Theme per ticker; unmapped tickers get 'unmapped' and are logged."""
    mapping = ticker_to_theme(theme_map)
    themes = tickers.map(mapping).fillna("unmapped")
    unmapped = sorted(set(tickers[themes == "unmapped"]))
    if unmapped:
        log.info("unmapped tickers (extend config/themes.yaml as needed): %s",
                 ", ".join(unmapped[:25]))
    return themes


def theme_mention_summary(mentions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate mention flow to theme level (the crowding overview)."""
    if mentions.empty:
        return pd.DataFrame(columns=["theme", "tickers", "mentions", "max_velocity_z"])
    df = mentions.copy()
    df["theme"] = classify(df["ticker"])
    agg = (
        df[df["theme"] != "unmapped"]
        .groupby("theme")
        .agg(
            tickers=("ticker", lambda s: ", ".join(s.head(6))),
            mentions=("mentions", "sum"),
            max_velocity_z=("velocity_z", "max"),
        )
        .reset_index()
        .sort_values("mentions", ascending=False)
    )
    return agg
