import json
import os
import pandas as pd

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


def apply_filters(df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    if config is None:
        config = load_config()

    mask = pd.Series(True, index=df.index)

    min_mc = config.get("min_market_cap")
    if min_mc is not None:
        mask &= df["Market Cap"].fillna(0) >= min_mc

    max_mc = config.get("max_market_cap")
    if max_mc is not None:
        mask &= df["Market Cap"].fillna(float("inf")) <= max_mc

    max_pe = config.get("max_pe")
    if max_pe is not None:
        mask &= df["P/E"].fillna(float("inf")) <= max_pe

    min_rev = config.get("min_revenue_growth")
    if min_rev is not None:
        mask &= df["Rev Growth %"].fillna(-float("inf")) >= min_rev

    min_vol = config.get("min_avg_volume")
    if min_vol is not None:
        mask &= df["Avg Volume"].fillna(0) >= min_vol

    return df[mask].copy()
