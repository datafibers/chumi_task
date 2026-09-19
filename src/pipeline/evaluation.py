"""Golden regression suite for model and prompt changes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from src.models import MarketSignal, RawMessage
from src.pipeline.context_assembly import assemble_contexts, format_context_for_llm
from src.pipeline.extraction import extract_signals
from src.pipeline.normalization import normalize_signals


def _load_cases(path: str) -> List[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _best_signal(signals: List[MarketSignal], expected: dict) -> MarketSignal | None:
    if signals:
        # Score all candidates instead of filtering by resource first. A model
        # may emit a commitment for the final reply with an unknown resource,
        # while earlier messages carry the canonical resource name.
        def score(item: MarketSignal) -> int:
            score_value = 0
            for field, value in expected.items():
                if _field_match(item, field, value):
                    score_value += 2 if field == "resource_entity" else 3
            return score_value

        return max(signals, key=score)
    return signals[0] if signals else None


def _field_match(signal: MarketSignal, field: str, expected: Any) -> bool:
    actual = getattr(signal, field, None)
    if field in {"price", "volume"}:
        return actual is not None and abs(float(actual) - float(expected)) <= max(0.01, abs(float(expected)) * 0.05)
    if hasattr(actual, "value"):
        actual = actual.value
    return actual == expected


def run_golden_suite(path: str = "data/golden_cases.jsonl", inactivity_seconds: int | None = None) -> Dict[str, Any]:
    cases = _load_cases(path)
    input_rows = sum(len(case.get("messages", [])) for case in cases)
    results = []
    total_checks = 0
    passed_checks = 0
    started = time.perf_counter()

    for case in cases:
        messages = [RawMessage.model_validate(item) for item in case["messages"]]
        contexts = assemble_contexts(messages, inactivity_seconds=inactivity_seconds)
        signals: List[MarketSignal] = []
        error = None
        try:
            for context in contexts:
                signals.extend(extract_signals(context, format_context_for_llm(context)))
            signals = normalize_signals(signals)
        except Exception as exc:
            error = str(exc)

        expected = case["expected"]
        checks: Dict[str, bool] = {}
        if expected.get("no_actionable_signal"):
            checks["no_actionable_signal"] = not signals
        elif expected.get("resource_entities"):
            actual_resources = {signal.resource_entity for signal in signals}
            checks["resource_entities"] = set(expected["resource_entities"]).issubset(actual_resources)
            signal = _best_signal(signals, {"resource_entity": expected["resource_entities"][0]})
            if signal:
                for field in ("signal_kind", "direction", "price_type"):
                    if field in expected:
                        checks[field] = _field_match(signal, field, expected[field])
        else:
            signal = _best_signal(signals, expected)
            for field, value in expected.items():
                if field == "no_actionable_signal":
                    continue
                # A multi-message context may legitimately produce separate
                # signals: the resource can be carried by the initial request
                # while the final reply carries transaction_status=commitment.
                checks[field] = any(_field_match(item, field, value) for item in signals)

        total_checks += len(checks)
        passed_checks += sum(checks.values())
        results.append(
            {
                "case_id": case["case_id"],
                "chat_count": len(messages),
                "context_count": len(contexts),
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
                "signals": [signal.model_dump(mode="json") for signal in signals],
                "error": error,
            }
        )

    return {
        "cases": len(cases),
        "input_rows": input_rows,
        "contexts": sum(item["context_count"] for item in results),
        "passed_cases": sum(item["passed"] for item in results),
        "checks": total_checks,
        "passed_checks": passed_checks,
        "accuracy": round(passed_checks / total_checks, 3) if total_checks else 0.0,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "context_window_seconds": inactivity_seconds,
        "results": results,
    }
