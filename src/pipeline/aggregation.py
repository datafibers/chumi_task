"""Aggregate compatible signals into interpretable market trends."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pandas as pd

from src.models import AggregatedTrend, Direction, MarketSignal


def signals_to_dataframe(signals: List[MarketSignal]) -> pd.DataFrame:
    return pd.DataFrame([signal.model_dump(mode="json") for signal in signals]) if signals else pd.DataFrame()


def _quantile(series: pd.Series, value: float) -> float | None:
    return float(series.quantile(value)) if not series.empty else None


def aggregate(signals: List[MarketSignal], now: datetime | None = None) -> List[AggregatedTrend]:
    if not signals:
        return []

    now = now or datetime.now(timezone.utc)
    rows: List[AggregatedTrend] = []
    frame = signals_to_dataframe(signals)
    for resource, group in frame.groupby("resource_entity", dropna=False):
        current = group[group["temporal_status"].isin(["current", "unknown"])]
        market = current[current["signal_kind"].isin(["offer", "request", "price_quote", "transaction"])]
        if market.empty:
            continue
        supply = market[market["direction"] == Direction.SUPPLY.value]
        demand = market[market["direction"] == Direction.DEMAND.value]

        # Price statistics only combine absolute prices with compatible units/currency.
        priced = market[(market["price"].notna()) & (market["price_type"] == "absolute")].copy()
        if not priced.empty:
            priced["price_key"] = priced["price_currency"].fillna("unknown") + ":" + priced["price_unit"].fillna("unknown")
            price_key = priced["price_key"].mode().iloc[0]
            prices = priced[priced["price_key"] == price_key]["price"].astype(float)
        else:
            prices = pd.Series(dtype=float)

        volume_supply = pd.to_numeric(supply["volume"], errors="coerce").dropna()
        volume_demand = pd.to_numeric(demand["volume"], errors="coerce").dropna()
        offer_ids = {value for value in market["offer_id"].dropna().tolist() if value}
        if not offer_ids:
            offer_ids = {f"signal:{idx}" for idx in market.index}

        availability = current["availability"].dropna().tolist()
        availability_state = "unknown"
        for candidate in ("available", "constrained", "unavailable"):
            if candidate in availability:
                availability_state = candidate
                break

        rows.append(
            AggregatedTrend(
                resource_entity=str(resource),
                supply_volume=float(volume_supply.sum()) if not volume_supply.empty else None,
                demand_volume=float(volume_demand.sum()) if not volume_demand.empty else None,
                supply_signals=len(supply),
                demand_signals=len(demand),
                median_price=float(prices.median()) if not prices.empty else None,
                price_p25=_quantile(prices, 0.25),
                price_p75=_quantile(prices, 0.75),
                price_range_min=float(prices.min()) if not prices.empty else None,
                price_range_max=float(prices.max()) if not prices.empty else None,
                sample_count=len(market),
                independent_offer_count=len(offer_ids),
                avg_confidence=round(float(current["confidence_score"].mean()), 2) if not current.empty else 0.0,
                availability_state=availability_state,
                last_updated=now.isoformat(),
            )
        )

    return sorted(rows, key=lambda item: item.sample_count, reverse=True)
