"""
Stage 5: Aggregation
Computes market trend statistics from a list of normalized MarketSignals using Pandas.

Why median instead of mean? Prices in informal markets have outliers (broker spam,
misquotes). Median is robust to these. We also report IQR (dispersion) so that
a single outlier doesn't silently distort the view.

Why confidence-weighted? A signal with confidence 0.3 (ambiguous units) should
contribute less to the price estimate than a signal with confidence 0.9 (explicit quote).
"""
import pandas as pd
from typing import List, Optional
from datetime import datetime, timezone
from src.models import MarketSignal, AggregatedTrend


ACTIVE_INTENTS = {"buy", "sell"}  # Only these count toward market depth


def signals_to_dataframe(signals: List[MarketSignal]) -> pd.DataFrame:
    """Convert a list of MarketSignals to a Pandas DataFrame."""
    records = [s.model_dump() for s in signals]
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    return df


def aggregate(signals: List[MarketSignal]) -> List[AggregatedTrend]:
    """
    Aggregate signals into per-resource market trends.
    Excludes irrelevant, observation_past signals from price statistics.
    """
    if not signals:
        return []

    df = signals_to_dataframe(signals)
    now_str = datetime.now(timezone.utc).isoformat()
    trends = []

    # Only active buy/sell signals participate in price aggregation
    active_df = df[df["intent"].isin(ACTIVE_INTENTS)]

    for resource, group in df.groupby("resource_entity"):
        active_group = active_df[active_df["resource_entity"] == resource]
        price_series = active_group["price"].dropna()

        sell_count = int((group["intent"] == "sell").sum())
        buy_count = int((group["intent"] == "buy").sum())
        independent_signals = len(group)
        avg_confidence = float(group["confidence_score"].mean())

        # Price stats (only from active signals with known prices)
        median_price: Optional[float] = None
        price_min: Optional[float] = None
        price_max: Optional[float] = None

        if not price_series.empty:
            # Confidence-weighted median approximation
            active_with_price = active_group[active_group["price"].notna()].copy()
            if not active_with_price.empty:
                # Sort by price, weight by confidence
                active_with_price = active_with_price.sort_values("price")
                weights = active_with_price["confidence_score"].values
                prices = active_with_price["price"].values
                # Weighted median: find price at cumulative weight >= 0.5
                cumulative = weights.cumsum() / weights.sum()
                median_idx = (cumulative >= 0.5).argmax()
                median_price = float(prices[median_idx])
                price_min = float(prices.min())
                price_max = float(prices.max())

        # Volume: sum sell-side only
        volume_series = active_group[active_group["intent"] == "sell"]["volume"].dropna()
        total_volume = float(volume_series.sum()) if not volume_series.empty else None

        trends.append(AggregatedTrend(
            resource_entity=str(resource),
            sell_count=sell_count,
            buy_count=buy_count,
            median_price=median_price,
            price_range_min=price_min,
            price_range_max=price_max,
            total_volume=total_volume,
            independent_signals=independent_signals,
            avg_confidence=round(avg_confidence, 2),
            last_updated=now_str,
        ))

    # Sort by number of independent signals descending
    trends.sort(key=lambda t: t.independent_signals, reverse=True)
    return trends
