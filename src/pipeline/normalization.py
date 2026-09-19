"""Deterministic resource normalization and message-level deduplication."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from src.models import MarketSignal


ALIAS_MAP: Dict[str, str] = {
    "claude": "Claude_API",
    "claude api": "Claude_API",
    "claude 3.5": "Claude_API",
    "claude 3.5 sonnet": "Claude_API",
    "claude 4": "Claude_API",
    "claude 4.2": "Claude_API",
    "sonnet": "Claude_API",
    "anthropic": "Claude_API",
    "openai": "OpenAI_Credits",
    "openai credits": "OpenAI_Credits",
    "openai api": "OpenAI_Credits",
    "openai accounts": "OpenAI_Credits",
    "gpt4": "OpenAI_Credits",
    "gpt-4": "OpenAI_Credits",
    "o1": "OpenAI_Credits",
    "openai o1": "OpenAI_Credits",
    "gemini": "Gemini_API",
    "gemini pro": "Gemini_API",
    "google api": "Gemini_API",
    "aws": "AWS_Compute",
    "aws accounts": "AWS_Compute",
    "amazon web services": "AWS_Compute",
    "gcp": "GCP_Compute",
    "google cloud": "GCP_Compute",
    "a100": "A100_GPU",
    "h100": "H100_GPU",
    "midjourney": "Midjourney_Sub",
    "midjourney annual subs": "Midjourney_Sub",
    "mj": "Midjourney_Sub",
    "cursor": "Cursor_Sub",
    "cursor pro": "Cursor_Sub",
}


def normalize_resource(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw.lower().strip())
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]
    for alias, canonical in sorted(ALIAS_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in key:
            return canonical
    return f"unknown:{key}" if key else "unknown:resource"


def signal_fingerprint(signal: MarketSignal) -> str:
    parts = "|".join(
        [
            signal.resource_entity,
            signal.signal_kind.value,
            signal.direction.value,
            signal.raw_price_str or str(signal.price),
            signal.price_currency or "",
            signal.price_unit or "",
            signal.raw_volume_str or str(signal.volume),
            signal.volume_unit or "",
            signal.price_type,
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def normalize_signals(signals: List[MarketSignal]) -> List[MarketSignal]:
    for signal in signals:
        signal.resource_entity = normalize_resource(signal.resource_entity)
        if signal.offer_id is None and signal.source_msg_ids:
            signal.offer_id = signal_fingerprint(signal)[:16]
    return signals


def deduplicate_signals(
    signals: List[MarketSignal],
    seen_hashes: Dict[str, datetime] | None = None,
    now: datetime | None = None,
) -> Tuple[List[MarketSignal], Dict[str, datetime]]:
    """Collapse exact repeated outputs in a bounded window, preserving provenance."""
    now = now or datetime.now(timezone.utc)
    seen_hashes = seen_hashes or {}
    cutoff = now - timedelta(hours=2)
    active = {key: value for key, value in seen_hashes.items() if value > cutoff}
    unique: List[MarketSignal] = []
    for signal in signals:
        fingerprint = signal_fingerprint(signal)
        if fingerprint in active:
            continue
        active[fingerprint] = now
        unique.append(signal)
    return unique, active


def run_normalization(
    signals: List[MarketSignal],
    seen_hashes: Dict[str, datetime] | None = None,
    active_state: Dict | None = None,
    now: datetime | None = None,
) -> Tuple[List[MarketSignal], Dict[str, datetime], Dict]:
    normalized = normalize_signals(signals)
    unique, hashes = deduplicate_signals(normalized, seen_hashes, now)
    # Lifecycle replacement is handled by the store using context/message IDs.
    return unique, hashes, active_state or {}
