"""
Streamlit Dashboard - Live Market Signal Intelligence Bot

Run with:
    streamlit run dashboard.py

Reads from data/chat_stream.jsonl (written by mock_producer.py)
and refreshes every REFRESH_INTERVAL_MS milliseconds.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline.ingestion import load_messages
from src.pipeline.context_assembly import assemble_contexts, format_context_for_llm
from src.pipeline.extraction import extract_signals
from src.pipeline.normalization import run_normalization
from src.pipeline.aggregation import aggregate

STREAM_FILE = "data/chat_stream.jsonl"
REFRESH_INTERVAL_MS = 5000

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Market Signal Bot",
    page_icon="🤖",
    layout="wide",
)

# ── Session state init ────────────────────────────────────────────────────────
if "all_signals" not in st.session_state:
    st.session_state.all_signals = []
if "seen_hashes" not in st.session_state:
    st.session_state.seen_hashes = {}
if "active_state" not in st.session_state:
    st.session_state.active_state = {}
if "last_msg_id" not in st.session_state:
    st.session_state.last_msg_id = None
if "price_history" not in st.session_state:
    st.session_state.price_history = []  # list of {time, resource, price}
if "processed_msg_ids" not in st.session_state:
    st.session_state.processed_msg_ids = set()

# ── Auto-refresh ──────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=REFRESH_INTERVAL_MS, key="autorefresh")
except ImportError:
    st.warning("Install streamlit-autorefresh for live updates: pip install streamlit-autorefresh")

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🤖 Market Signal Intelligence Bot")
st.caption(f"Live feed from `{STREAM_FILE}` · Refreshes every {REFRESH_INTERVAL_MS//1000}s · "
           f"Last update: {datetime.now().strftime('%H:%M:%S')}")
st.divider()

# ── Load & process new messages ───────────────────────────────────────────────
stream_path = Path(STREAM_FILE)
new_signals = []

if stream_path.exists():
    all_messages = load_messages(STREAM_FILE)

    # Only process messages we haven't seen yet
    new_messages = [m for m in all_messages if m.msg_id not in st.session_state.processed_msg_ids]

    if new_messages:
        with st.spinner(f"Processing {len(new_messages)} new message(s)..."):
            contexts = assemble_contexts(new_messages)
            for context in contexts:
                context_text = format_context_for_llm(context)
                signals = extract_signals(context, context_text)

                if signals:
                    signals, st.session_state.seen_hashes, st.session_state.active_state = (
                        run_normalization(
                            signals,
                            st.session_state.seen_hashes,
                            st.session_state.active_state,
                        )
                    )
                    new_signals.extend(signals)

            # Mark these messages as processed
            st.session_state.processed_msg_ids.update(m.msg_id for m in new_messages)

        # Append new signals and price history
        st.session_state.all_signals.extend(new_signals)
        now_str = datetime.now().strftime("%H:%M:%S")
        for sig in new_signals:
            if sig.price is not None and sig.intent in ("buy", "sell"):
                st.session_state.price_history.append({
                    "time": now_str,
                    "resource": sig.resource_entity,
                    "price": sig.price,
                    "intent": sig.intent,
                })

# ── Market Trends ─────────────────────────────────────────────────────────────
trends = aggregate(st.session_state.all_signals)

if not trends:
    st.info("⏳ Waiting for data... Start `mock_producer.py` in a separate terminal.")
else:
    # Top metrics row
    cols = st.columns(min(len(trends), 4))
    for i, trend in enumerate(trends[:4]):
        with cols[i]:
            price_display = f"${trend.median_price:.2f}" if trend.median_price else "N/A"
            delta = f"↑{trend.sell_count} sell  ↓{trend.buy_count} buy"
            st.metric(
                label=trend.resource_entity.replace("_", " "),
                value=price_display,
                delta=delta,
            )

    st.divider()

    # Market depth table
    st.subheader("📊 Market Depth")
    trend_data = []
    for t in trends:
        price_range = ""
        if t.price_range_min is not None and t.price_range_max is not None:
            price_range = f"${t.price_range_min:.2f} – ${t.price_range_max:.2f}"
        trend_data.append({
            "Resource": t.resource_entity.replace("_", " "),
            "Median Price": f"${t.median_price:.2f}" if t.median_price else "—",
            "Price Range": price_range or "—",
            "Sell Signals": t.sell_count,
            "Buy Signals": t.buy_count,
            "Independent Signals": t.independent_signals,
            "Avg Confidence": f"{t.avg_confidence:.0%}",
        })
    st.dataframe(pd.DataFrame(trend_data), use_container_width=True, hide_index=True)

# ── Price history chart ───────────────────────────────────────────────────────
if st.session_state.price_history:
    st.subheader("📈 Price History (Active Signals)")
    hist_df = pd.DataFrame(st.session_state.price_history)
    # Pivot for chart: resources as columns
    pivot = hist_df.pivot_table(index="time", columns="resource", values="price", aggfunc="mean")
    st.line_chart(pivot)

st.divider()

# ── Raw signal feed ───────────────────────────────────────────────────────────
if st.session_state.all_signals:
    st.subheader(f"📋 All Extracted Signals ({len(st.session_state.all_signals)} total)")
    signal_rows = []
    for s in reversed(st.session_state.all_signals):
        signal_rows.append({
            "Resource": s.resource_entity.replace("_", " "),
            "Intent": s.intent,
            "Price": f"${s.price:.2f}" if s.price else s.raw_price_str or "—",
            "Volume": s.raw_volume_str or (str(s.volume) if s.volume else "—"),
            "Confidence": f"{s.confidence_score:.0%}",
            "Explanation": s.explanation[:80] + "..." if len(s.explanation) > 80 else s.explanation,
            "Source Msgs": ", ".join(s.source_msg_ids),
        })
    st.dataframe(pd.DataFrame(signal_rows), use_container_width=True, hide_index=True)
