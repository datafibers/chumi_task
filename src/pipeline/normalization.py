"""
Stage 4: Normalization & Deduplication

1. Alias normalization: maps informal resource names to canonical IDs.
2. Hash-based deduplication: prevents broker spam from inflating signal count.
3. State overwrite: if same user updates the same resource within a window, keep latest.
"""
import hashlib
from typing import List, Dict, Tuple
from datetime import datetime, timezone, timedelta
from src.models import MarketSignal

# ── Alias dictionary ─────────────────────────────────────────────────────────
# Maps lowercase aliases -> canonical resource_entity
ALIAS_MAP: Dict[str, str] = {
    # Claude / Anthropic
    "claude": "Claude_API",
    "claude api": "Claude_API",
    "claude 3.5": "Claude_API",
    "claude 3.5 sonnet": "Claude_API",
    "claude 4": "Claude_API",
    "claude 4.2": "Claude_API",
    "sonnet": "Claude_API",
    "anthropic": "Claude_API",
    # OpenAI
    "openai": "OpenAI_Credits",
    "openai credits": "OpenAI_Credits",
    "openai api": "OpenAI_Credits",
    "gpt4": "OpenAI_Credits",
    "gpt-4": "OpenAI_Credits",
    "o1": "OpenAI_Credits",
    "openai o1": "OpenAI_Credits",
    "openai accounts": "OpenAI_Credits",
    # Google / Gemini
    "gemini": "Gemini_API",
    "gemini pro": "Gemini_API",
    "google api": "Gemini_API",
    # AWS Compute
    "aws": "AWS_Compute",
    "amazon web services": "AWS_Compute",
    "aws accounts": "AWS_Compute",
    # GCP Compute
    "gcp": "GCP_Compute",
    "google cloud": "GCP_Compute",
    # GPU Compute
    "a100": "A100_GPU",
    "h100": "H100_GPU",
    "8-card a100": "A100_GPU",
    "8-card h100": "H100_GPU",
    "8 gpu": "H100_GPU",
    # Midjourney
    "midjourney": "Midjourney_Sub",
    "mj": "Midjourney_Sub",
    "midjourney sub": "Midjourney_Sub",
    "midjourney annual": "Midjourney_Sub",
    # Cursor
    "cursor": "Cursor_Sub",
    "cursor pro": "Cursor_Sub",
}

# Deduplication window: signals with same hash within this window are duplicates
DEDUP_WINDOW_HOURS = 2

# State overwrite window: same user + same resource within this window = update
STATE_OVERWRITE_WINDOW_MINUTES = 30


def normalize_resource(raw: str) -> str:
    """Map a raw resource string to its canonical name."""
    key = raw.lower().strip()
    return ALIAS_MAP.get(key, raw)  # Unknown resources kept as-is


def signal_hash(signal: MarketSignal) -> str:
    """Generate a content fingerprint for deduplication."""
    parts = f"{signal.intent}|{signal.resource_entity}|{signal.price}|{signal.volume}"
    return hashlib.md5(parts.encode()).hexdigest()


def normalize_signals(signals: List[MarketSignal]) -> List[MarketSignal]:
    """Apply alias normalization to all signals."""
    for signal in signals:
        signal.resource_entity = normalize_resource(signal.resource_entity)
    return signals


def deduplicate_signals(
    new_signals: List[MarketSignal],
    seen_hashes: Dict[str, datetime],
    now: datetime = None,
) -> Tuple[List[MarketSignal], Dict[str, datetime]]:
    """
    Remove signals whose content hash has been seen within DEDUP_WINDOW_HOURS.
    Returns (unique_signals, updated_seen_hashes).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=DEDUP_WINDOW_HOURS)

    # Purge expired hashes
    seen_hashes = {h: t for h, t in seen_hashes.items() if t > cutoff}

    unique = []
    for signal in new_signals:
        h = signal_hash(signal)
        if h not in seen_hashes:
            unique.append(signal)
            seen_hashes[h] = now
        else:
            print(f"  [Dedup] Duplicate suppressed: {signal.resource_entity} @ {signal.price}")

    return unique, seen_hashes


def apply_state_overwrite(
    new_signals: List[MarketSignal],
    active_state: Dict[Tuple[str, str], Tuple[MarketSignal, datetime]],
    now: datetime = None,
) -> Tuple[List[MarketSignal], Dict]:
    """
    For signals from the same source that update the same resource within the overwrite window,
    replace the old signal with the new one (handle self-corrections that slip through context assembly).

    active_state key: (user_id_from_provenance, resource_entity)
    Note: user_id is approximated from source_msg_ids for now.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=STATE_OVERWRITE_WINDOW_MINUTES)

    # Purge stale state entries
    active_state = {k: v for k, v in active_state.items() if v[1] > cutoff}

    result = []
    for signal in new_signals:
        # Use first source_msg_id as a proxy for user key
        user_key = signal.source_msg_ids[0] if signal.source_msg_ids else "unknown"
        state_key = (user_key[:3], signal.resource_entity)  # prefix of msg_id as user proxy

        if state_key in active_state:
            old_signal, old_time = active_state[state_key]
            print(f"  [State] Overwriting old signal for {signal.resource_entity}: "
                  f"{old_signal.price} -> {signal.price}")

        active_state[state_key] = (signal, now)
        result.append(signal)

    return result, active_state


def run_normalization(
    signals: List[MarketSignal],
    seen_hashes: Dict[str, datetime],
    active_state: Dict,
    now: datetime = None,
) -> Tuple[List[MarketSignal], Dict, Dict]:
    """Full normalization pipeline: normalize -> deduplicate -> state overwrite."""
    signals = normalize_signals(signals)
    signals, seen_hashes = deduplicate_signals(signals, seen_hashes, now)
    signals, active_state = apply_state_overwrite(signals, active_state, now)
    return signals, seen_hashes, active_state
