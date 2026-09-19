"""Two-panel Streamlit UI: Dashboard and Control."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from src.models import MarketSignal
from src.pipeline.aggregation import aggregate
from src.pipeline.context_assembly import assemble_contexts, context_key, format_context_for_llm
from src.pipeline.evaluation import run_golden_suite
from src.pipeline.extraction import extract_signals
from src.pipeline.ingestion import load_messages
from src.pipeline.normalization import run_normalization
from src.pipeline.store import SignalStore


SOURCE_FILE = Path(os.getenv("CHAT_SOURCE_FILE", "data/chat_messages.jsonl"))
STREAM_FILE = os.getenv("CHAT_STREAM_FILE", "data/chat_stream.jsonl")
STORE_FILE = os.getenv("MARKET_DB_FILE", "data/market_signal.db")
SNAPSHOT_FILE = Path(os.getenv("SNAPSHOT_FILE", "data/snapshot.json"))
USER_SETTINGS_FILE = Path(".streamlit/user_settings.json")
GOLDEN_REPORT_FILE = Path(".streamlit/last_golden_report.json")

# Curated OpenRouter models that support reliable JSON/structured extraction.
# The custom option keeps the UI usable when OpenRouter adds a newer model.
OPENROUTER_MODELS = {
    "google/gemini-3.8-flash": "Gemini 3.8 Flash · newest fast model",
    "google/gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview · frontier reasoning",
    "google/gemini-2.5-flash": "Gemini 2.5 Flash · fast / cost-conscious",
    "google/gemini-2.5-pro": "Gemini 2.5 Pro · higher reasoning quality",
    "anthropic/claude-sonnet-4.5": "Claude Sonnet 4.5 · strong extraction quality",
    "openai/gpt-4.1-mini": "GPT-4.1 Mini · fast structured output",
    "openai/gpt-4.1": "GPT-4.1 · high quality / higher cost",
}

GOLDEN_CASE_HELP = {
    "correction": "A later message corrects the earlier price; only the final value should remain.",
    "demand-bound": "Tests demand direction and an upper price bound such as 'below 4'.",
    "gpu-supply": "Tests A100 resource recognition and an offered quantity of eight GPUs.",
    "historical": "A historical price must not be treated as a current quote.",
    "bundled-offer": "One message contains AWS and GCP; the extractor must split it into two signals.",
    "commitment": "The Need → I have → Deal reply chain should become a commitment.",
    "availability": "No explicit quote; reduced availability should be marked constrained.",
    "irrelevant": "An unrelated fact must not create an actionable market signal.",
}

GOLDEN_FIELD_HELP = {
    "Case": "Golden scenario identifier.",
    "Chats": "Raw chat messages included in this golden scenario.",
    "Contexts": "Context batches produced after reply-chain and time-window assembly.",
    "Passed": "True only when every expected field check passes.",
    "resource_entity": "Canonical resource name, such as A100_GPU or OpenAI_Credits.",
    "signal_kind": "One of offer, request, price_quote, availability, or transaction.",
    "direction": "Market direction: supply, demand, or unknown.",
    "price": "Whether the numeric price matches the expected value.",
    "price_type": "Price semantics such as absolute, upper_bound, range, or percentage_discount.",
    "volume": "Whether the quantity matches the expected value.",
    "transaction_status": "none, inquiry, negotiation, commitment, completed, or cancelled.",
    "temporal_status": "current, historical, future, or unknown.",
    "availability": "available, unavailable, constrained, or unknown.",
    "Error": "Model, JSON parsing, or pipeline error; blank means no error.",
}


def _ui_value(value):
    """Render missing values as an empty cell instead of the word None."""
    return "" if value is None else value


def _load_user_settings() -> None:
    """Restore UI settings from a local, git-ignored file when present."""
    if st.session_state.get("_user_settings_loaded", False):
        return
    if not USER_SETTINGS_FILE.exists():
        st.session_state["_user_settings_loaded"] = True
        return
    try:
        saved = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.session_state["_user_settings_loaded"] = True
        return
    for key in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODEL", "REPORT_REFRESH_SECONDS", "USE_FAKE_LLM", "GOLDEN_MIN_ACCURACY", "CONTEXT_WINDOW_SECONDS"):
        if key in saved and saved[key] not in (None, ""):
            os.environ[key] = str(saved[key])
    if "USE_FAKE_LLM" in saved:
        st.session_state["runtime_live_toggle"] = str(saved["USE_FAKE_LLM"]).lower() not in {"1", "true", "yes"}
    st.session_state["_user_settings_loaded"] = True


def _load_golden_report():
    if not GOLDEN_REPORT_FILE.exists():
        return None
    try:
        return json.loads(GOLDEN_REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_golden_report(report) -> None:
    GOLDEN_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = GOLDEN_REPORT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(GOLDEN_REPORT_FILE)


def _init_settings() -> None:
    st.session_state.setdefault("runtime_model", os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash"))
    st.session_state.setdefault("runtime_fallback", os.getenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.5-pro"))
    st.session_state.setdefault("runtime_refresh", int(os.getenv("REPORT_REFRESH_SECONDS", "5")))
    st.session_state.setdefault("runtime_context_window", int(os.getenv("CONTEXT_WINDOW_SECONDS", "120")))
    st.session_state.setdefault("runtime_fake", os.getenv("USE_FAKE_LLM", "0").lower() in {"1", "true", "yes"})
    st.session_state.setdefault("runtime_live_toggle", not st.session_state.runtime_fake)
    st.session_state.setdefault("golden_min_accuracy", float(os.getenv("GOLDEN_MIN_ACCURACY", "0.75")))
    st.session_state.setdefault("golden_report", _load_golden_report())
    page_from_url = st.query_params.get("page") if hasattr(st, "query_params") else None
    page_labels = {"dashboard": "📊 Dashboard", "settings": "⚙️ Settings", "control": "🧪 Control"}
    st.session_state.setdefault("active_page", page_labels.get(page_from_url, "📊 Dashboard"))


def apply_runtime_settings(model: str, fallback_model: str, refresh_seconds: int, fake_llm: bool, api_key: str, context_window: int | None = None) -> None:
    st.session_state.runtime_model = model.strip() or "google/gemini-2.5-flash"
    st.session_state.runtime_fallback = fallback_model.strip() or "google/gemini-2.5-pro"
    st.session_state.runtime_refresh = max(1, int(refresh_seconds))
    if context_window is not None:
        st.session_state.runtime_context_window = max(10, int(context_window))
    st.session_state.runtime_fake = fake_llm
    os.environ["OPENROUTER_MODEL"] = st.session_state.runtime_model
    os.environ["OPENROUTER_FALLBACK_MODEL"] = st.session_state.runtime_fallback
    os.environ["REPORT_REFRESH_SECONDS"] = str(st.session_state.runtime_refresh)
    os.environ["USE_FAKE_LLM"] = "1" if fake_llm else "0"
    os.environ["CONTEXT_WINDOW_SECONDS"] = str(st.session_state.runtime_context_window)
    if api_key.strip():
        os.environ["OPENROUTER_API_KEY"] = api_key.strip()
    settings = {
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
        "OPENROUTER_MODEL": st.session_state.runtime_model,
        "OPENROUTER_FALLBACK_MODEL": st.session_state.runtime_fallback,
        "REPORT_REFRESH_SECONDS": st.session_state.runtime_refresh,
        "USE_FAKE_LLM": "1" if fake_llm else "0",
        "GOLDEN_MIN_ACCURACY": st.session_state.golden_min_accuracy,
        "CONTEXT_WINDOW_SECONDS": st.session_state.runtime_context_window,
    }
    USER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = USER_SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temporary.replace(USER_SETTINGS_FILE)


def write_demo_stream() -> None:
    messages = load_messages(str(SOURCE_FILE))
    path = Path(STREAM_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for message in messages:
            payload = message.model_dump(mode="json")
            payload["ingested_at"] = datetime.now(timezone.utc).isoformat()
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_snapshot(trends, signals: list[MarketSignal], failures: list[str], messages) -> None:
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    latest = max(messages, key=lambda item: item.event_time) if messages else None
    payload = {
        "version": len(signals),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_event_time": latest.timestamp if latest else None,
        "last_processed_message_id": latest.msg_id if latest else None,
        "rows": [trend.model_dump(mode="json") for trend in trends],
        "signal_count": len(signals),
        "pipeline_errors": failures,
    }
    temporary = SNAPSHOT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SNAPSHOT_FILE)


def process_new_contexts(store: SignalStore, messages) -> tuple[int, list[str]]:
    processed = 0
    errors: list[str] = []
    for context in assemble_contexts(messages, st.session_state.runtime_context_window):
        key = context_key(context)
        if store.has_context(key):
            continue
        try:
            extracted = extract_signals(context, format_context_for_llm(context))
            normalized, _, _ = run_normalization(extracted)
            store.replace_context_signals(key, [item.msg_id for item in context], normalized)
            processed += 1
        except Exception as exc:
            store.record_failure(key, str(exc))
            errors.append(f"context {key}: {exc}")
    return processed, errors


def render_settings() -> None:
    st.caption("Configure the model provider separately from application behavior.")

    previous_fake = st.session_state.runtime_fake
    mode = st.radio("Run mode", ["Offline", "Online (OpenRouter)"], index=1 if st.session_state.runtime_live_toggle else 0, horizontal=True, key="runtime_mode_radio")
    live_mode = mode == "Online (OpenRouter)"
    fake_llm = not live_mode
    # Mode changes take effect immediately, even before the rest of the form is saved.
    st.session_state.runtime_fake = fake_llm
    os.environ["USE_FAKE_LLM"] = "1" if fake_llm else "0"
    if fake_llm != previous_fake:
        apply_runtime_settings(st.session_state.runtime_model, st.session_state.runtime_fallback, st.session_state.runtime_refresh, fake_llm, "", st.session_state.runtime_context_window)
    if fake_llm:
        st.success("OFFLINE MODE  ·  No OpenRouter calls  ·  deterministic demo extractor", icon="🧪")
    else:
        st.info("LIVE MODE  ·  Signals will be extracted through OpenRouter", icon="☁️")

    with st.expander("OpenRouter settings", expanded=not fake_llm):
        if not fake_llm:
            with st.form("openrouter_configuration"):
                model_options = list(OPENROUTER_MODELS)
                if st.session_state.runtime_model not in model_options:
                    model_options.append(st.session_state.runtime_model)
                model = st.selectbox("Primary model", options=model_options, index=model_options.index(st.session_state.runtime_model), format_func=lambda value: OPENROUTER_MODELS.get(value, f"Custom · {value}"))
                fallback_options = list(OPENROUTER_MODELS)
                if st.session_state.runtime_fallback not in fallback_options:
                    fallback_options.append(st.session_state.runtime_fallback)
                fallback_model = st.selectbox("Fallback model", options=fallback_options, index=fallback_options.index(st.session_state.runtime_fallback), format_func=lambda value: OPENROUTER_MODELS.get(value, f"Custom · {value}"))
                custom_model = st.text_input("Custom model slug (optional)", placeholder="provider/model-name")
                api_key = st.text_input("OpenRouter API key", value=os.getenv("OPENROUTER_API_KEY", ""), type="password", help="Stored locally in the git-ignored user settings file.")
                st.caption(f"Key configured: {'yes' if os.getenv('OPENROUTER_API_KEY') else 'no'} · The value is masked.")
                router_saved = st.form_submit_button("Save OpenRouter settings")
            if router_saved:
                apply_runtime_settings(custom_model.strip() or model, fallback_model, st.session_state.runtime_refresh, fake_llm, api_key, st.session_state.runtime_context_window)
                st.success("OpenRouter settings saved locally.")
        else:
            st.caption("OpenRouter settings are hidden while Offline mode is selected.")

    with st.expander("Application settings", expanded=True):
        with st.form("application_configuration"):
            refresh = st.number_input("Dashboard refresh frequency (seconds)", min_value=1, max_value=300, value=st.session_state.runtime_refresh)
            context_window = st.number_input("Combined message window (seconds)", min_value=10, max_value=3600, value=st.session_state.runtime_context_window, help="Messages in the same group within this inactivity window are sent to the model as one context.")
            min_accuracy = st.number_input("Minimum acceptable golden field accuracy", min_value=0.5, max_value=1.0, value=st.session_state.golden_min_accuracy, step=0.01, format="%.2f")
            app_saved = st.form_submit_button("Save application settings")
        if app_saved:
            st.session_state.golden_min_accuracy = float(min_accuracy)
            apply_runtime_settings(st.session_state.runtime_model, st.session_state.runtime_fallback, refresh, fake_llm, "", context_window)
            os.environ["GOLDEN_MIN_ACCURACY"] = str(st.session_state.golden_min_accuracy)
            st.success("Application settings saved locally.")

    configured = bool(os.getenv("OPENROUTER_API_KEY"))
    if st.session_state.runtime_fake:
        st.caption("Current mode: Offline demo")
    else:
        st.caption(f"Current mode: OpenRouter · key configured: {'yes' if configured else 'no'}")

def render_control() -> None:
    st.caption("Run golden regression tests before processing the demo fixture.")

    st.divider()
    st.subheader("Golden regression test")
    st.write("Runs the current model and prompt against the hand-labeled cases in `data/golden_cases.jsonl`.")
    if st.button("Run golden tests", type="secondary"):
        os.environ["OPENROUTER_MODEL"] = st.session_state.runtime_model
        os.environ["OPENROUTER_FALLBACK_MODEL"] = st.session_state.runtime_fallback
        os.environ["USE_FAKE_LLM"] = "1" if st.session_state.runtime_fake else "0"
        with st.spinner("Running golden cases..."):
            st.session_state.golden_report = run_golden_suite()
            _save_golden_report(st.session_state.golden_report)

    report = st.session_state.golden_report
    if report:
        # Backward compatibility for reports saved before chat/context counts
        # were added to the evaluation result.
        if "input_rows" not in report:
            chat_counts = [item.get("chat_count") for item in report.get("results", []) if "chat_count" in item]
            report["input_rows"] = sum(chat_counts) if chat_counts else "—"
        if "contexts" not in report:
            context_counts = [item.get("context_count") for item in report.get("results", []) if "context_count" in item]
            report["contexts"] = sum(context_counts) if context_counts else "—"
        cols = st.columns(6)
        cols[0].metric("Cases", report["cases"], help="Number of labeled golden scenarios.")
        cols[1].metric("Chats tested", report["input_rows"], help="Total raw chat messages across all golden scenarios.")
        cols[2].metric("Contexts sent", report["contexts"], help="Context batches sent to the model after reply/thread assembly.")
        cols[3].metric("Passed cases", report["passed_cases"], help="A case passes only when every expected field check passes.")
        cols[4].metric("Field accuracy", f"{report['accuracy']:.0%}", help="Passed field checks divided by total field checks.")
        cols[5].metric("Elapsed", f"{report['elapsed_seconds']:.1f}s", help="Time spent running the suite.")
        if report["accuracy"] >= st.session_state.golden_min_accuracy:
            st.success(f"PASS — accuracy is within the configured tolerance (≥ {st.session_state.golden_min_accuracy:.0%}). Demo processing is enabled.")
        else:
            st.error(f"HOLD — accuracy is below the configured threshold ({st.session_state.golden_min_accuracy:.0%}). Review failures before running the demo.")
        case_rows = [
            {"Case": item["case_id"], "Chats": item["chat_count"], "Contexts": item["context_count"], "Passed": item["passed"], **item["checks"], "Error": item["error"] or ""}
            for item in report["results"]
        ]
        frame = pd.DataFrame(case_rows).fillna("")
        column_config = {
            name: st.column_config.TextColumn(name, help=GOLDEN_FIELD_HELP.get(name, "Golden field check result."))
            for name in frame.columns
            if name not in {"Passed"}
        }
        column_config["Passed"] = st.column_config.CheckboxColumn("Passed", help=GOLDEN_FIELD_HELP["Passed"])
        selection = st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
            on_select="rerun",
            selection_mode="single-row",
            key="golden_results_table",
        )
        selected_case = None
        if hasattr(selection, "selection") and selection.selection.rows:
            selected_row = selection.selection.rows[0]
            if selected_row < len(report["results"]):
                selected_case = report["results"][selected_row]["case_id"]
        if selected_case:
            st.info(f"**{selected_case}** — {GOLDEN_CASE_HELP.get(selected_case, 'No scenario description available.')}")
        else:
            st.caption("Click a case row to view its description.")
        for item in report["results"]:
            if not item["passed"]:
                with st.expander(f"Failure: {item['case_id']}"):
                    st.json(item)

    st.divider()
    st.subheader("Demo replay")
    st.write("Loads the adversarial fixture into the stream, resets derived state, and processes it with the current configuration.")
    demo_blocked = bool(st.session_state.golden_report and st.session_state.golden_report["accuracy"] < st.session_state.golden_min_accuracy)
    if st.button("Run demo", type="primary", disabled=demo_blocked):
        store = SignalStore(STORE_FILE)
        store.reset()
        write_demo_stream()
        messages = load_messages(STREAM_FILE)
        with st.spinner("Processing demo messages..."):
            processed, errors = process_new_contexts(store, messages)
        st.success(f"Processed {processed} contexts and stored {len(store.load_signals())} signals.")
        if errors:
            st.warning("Some contexts failed; inspect the Dashboard pipeline issues panel.")
    if demo_blocked:
        st.caption("Demo is disabled until the latest golden run meets the configured accuracy threshold.")


def render_dashboard() -> None:
    refresh_seconds = st.session_state.runtime_refresh
    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=refresh_seconds * 1000, key="market_signal_refresh")
    except ImportError:
        st.caption("Install streamlit-autorefresh for automatic refresh.")

    st.caption(f"Stream: `{STREAM_FILE}` · Refresh: every {refresh_seconds}s")

    store = SignalStore(STORE_FILE)
    messages = load_messages(STREAM_FILE)
    processed_count, current_errors = process_new_contexts(store, messages)
    signals = store.load_signals()
    trends = aggregate(signals)
    failures = current_errors + store.load_failures()
    write_snapshot(trends, signals, failures, messages)

    columns = st.columns(4)
    columns[0].metric("Messages", len(messages))
    columns[1].metric("Signals", len(signals))
    columns[2].metric("Resources", len(trends))
    columns[3].metric("New contexts", processed_count)

    if st.session_state.runtime_fake:
        st.info("Offline fake extractor is enabled.")
    if failures:
        with st.expander(f"Pipeline issues ({len(failures)})"):
            st.code("\n".join(failures[-10:]))

    if not trends:
        st.info("No signals yet. Use Control → Run demo, or start `python mock_producer.py --reset --interval 1`.")
        return

    st.subheader("Market snapshot")
    trend_rows = [
        {
            "Resource": trend.resource_entity.replace("_", " "),
            "Supply volume": _ui_value(trend.supply_volume),
            "Demand volume": _ui_value(trend.demand_volume),
            "Median price": _ui_value(trend.median_price),
            "P25": _ui_value(trend.price_p25),
            "P75": _ui_value(trend.price_p75),
            "Samples": trend.sample_count,
            "Independent offers": trend.independent_offer_count,
            "Confidence": f"{trend.avg_confidence:.0%}",
            "Availability": trend.availability_state,
        }
        for trend in trends
    ]
    st.dataframe(pd.DataFrame(trend_rows), use_container_width=True, hide_index=True)

    chart_rows = [{"resource": trend.resource_entity, "median_price": trend.median_price} for trend in trends if trend.median_price is not None]
    if chart_rows:
        st.subheader("Comparable price points")
        st.bar_chart(pd.DataFrame(chart_rows).set_index("resource"))

    st.subheader(f"Extracted signals ({len(signals)})")
    signal_rows = [
        {
            "Resource": signal.resource_entity.replace("_", " "),
            "Kind": signal.signal_kind.value,
            "Direction": signal.direction.value,
            "Price": _ui_value(signal.raw_price_str or signal.price),
            "Volume": _ui_value(signal.raw_volume_str or signal.volume),
            "Availability": signal.availability.value,
            "Confidence": f"{signal.confidence_score:.0%}",
            "Evidence": ", ".join(signal.source_msg_ids),
            "Explanation": signal.explanation,
        }
        for signal in reversed(signals)
    ]
    if signal_rows:
        signal_frame = pd.DataFrame(signal_rows)
        signal_config = {
            "Resource": st.column_config.TextColumn("Resource", width="medium"),
            "Kind": st.column_config.TextColumn("Kind", width="small"),
            "Direction": st.column_config.TextColumn("Direction", width="small"),
            "Price": st.column_config.TextColumn("Price", width="small"),
            "Volume": st.column_config.TextColumn("Volume", width="small"),
            "Availability": st.column_config.TextColumn("Availability", width="small"),
            "Confidence": st.column_config.TextColumn("Confidence", width="small"),
            "Evidence": st.column_config.TextColumn("Evidence", width="medium"),
            "Explanation": st.column_config.TextColumn("Explanation", width="large"),
        }
        st.dataframe(signal_frame, use_container_width=True, hide_index=True, column_config=signal_config, height=520)
    else:
        st.caption("No extracted signals yet.")


_load_user_settings()
_init_settings()
st.set_page_config(page_title="Market Signal Bot", page_icon="📡", layout="wide")
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #101827 0%, #17243a 100%); }
    [data-testid="stSidebar"] * { color: #e7eef9; }
    [data-testid="stMetric"] { background: rgba(30, 54, 85, .08); border: 1px solid rgba(100, 140, 190, .18); border-radius: 12px; padding: 10px; }
    div[data-testid="stAlert"] { border-radius: 12px; }
    div[role="radiogroup"] { gap: 8px; margin: 0 0 1rem 0; }
    div[role="radiogroup"] label { border: 1px solid rgba(100, 140, 190, .25); border-radius: 10px; padding: 5px 14px; background: rgba(30, 54, 85, .06); }
    div[role="radiogroup"] label:has(input:checked) { background: rgba(30, 54, 85, .14); border-color: rgba(30, 54, 85, .45); color: inherit; box-shadow: inset 0 -2px 0 rgba(30, 54, 85, .65); }
    div[role="radiogroup"] label p { font-weight: 600; }
    h1 { margin-top: 0; margin-bottom: 0.25rem; }
    [data-testid="stAppViewContainer"] .main .block-container { padding-top: 2rem; }
    div[data-testid="stAlert"] { margin-top: 0; margin-bottom: 0.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)
if st.session_state.runtime_fake:
    st.warning("🧪 OFFLINE DEMO MODE · Deterministic fake extractor · No OpenRouter calls")
else:
    st.info(f"☁️ LIVE MODEL · Primary: `{st.session_state.runtime_model}` · Fallback: `{st.session_state.runtime_fallback}`")
header_title, header_nav = st.columns([1.7, 1.3])
with header_title:
    st.title("Market Signal Intelligence Bot")
with header_nav:
    page = st.radio("", ["📊 Dashboard", "⚙️ Settings", "🧪 Control"], key="active_page", horizontal=True, label_visibility="collapsed")
page_query = {"📊 Dashboard": "dashboard", "⚙️ Settings": "settings", "🧪 Control": "control"}[page]
if hasattr(st, "query_params") and st.query_params.get("page") != page_query:
    st.query_params["page"] = page_query
if page.endswith("Settings"):
    page = "Settings"
elif page.endswith("Control"):
    page = "Control"
else:
    page = "Dashboard"
if page == "Settings":
    render_settings()
elif page == "Control":
    render_control()
else:
    render_dashboard()
