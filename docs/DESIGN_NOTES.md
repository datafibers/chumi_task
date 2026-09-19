# Design Notes: Market Signal Intelligence Bot

## 1. Problem Definition

The system turns noisy group-chat messages into time-bounded market observations for AI resources such as model/API access, credits, accounts, quotas, and compute.

The unit of analysis is a **market signal**, not a message. A signal is an observation about a resource, expressed by a source at a point in time, with enough evidence to explain how it was derived. One message can produce multiple signals, and several messages can jointly produce one signal.

The system is conservative: when a price, unit, resource identity, or temporal status is unclear, it preserves the raw value and lowers confidence or abstains instead of inventing a normalization.

## 2. Design Goals and Non-goals

### Goals

- Extract supply, demand, price, availability, and transaction observations.
- Resolve meaning that depends on replies, corrections, quoted messages, or recent conversation state.
- Preserve raw evidence and source lineage for every derived signal.
- Normalize comparable resources and units while retaining unknown resources.
- Produce an interpretable market snapshot with freshness and uncertainty.
- Make extraction and aggregation quality measurable with adversarial examples.

### Non-goals for the timebox

- Direct production integration with Telegram or WeChat.
- Fully automated entity ontology management.
- Treating every conversational statement as a reliable market quote.
- Building Kafka/Flink infrastructure before the signal semantics are stable.

## 3. Conceptual Data Model

The pipeline uses five explicit concepts:

1. **RawMessage**: an immutable platform event with `message_id`, `platform`, `group_id`, `user_id`, `event_time`, `ingested_at`, `text`, `reply_to`, and forwarding metadata.
2. **Context**: the smallest set of related messages required to interpret one or more signals. It keeps message order and records why each message was included.
3. **MarketSignal**: a structured observation derived from a context. It contains a resource, semantic type, direction, currentness, optional price/quantity with units, confidence, and evidence references.
4. **OfferEvent**: an inferred underlying offer or request that may be mentioned repeatedly or forwarded across groups.
5. **MarketSnapshot**: a time-windowed aggregation of compatible signals, split by resource, direction, price semantics, and freshness.

The minimum signal dimensions are:

```text
resource_id / raw_resource_text
signal_kind: offer | request | price_quote | availability | transaction
direction: supply | demand | unknown
temporal_status: current | historical | future | unknown
transaction_status: none | inquiry | negotiation | commitment | completed | cancelled
price_value / price_currency / price_unit / price_type
quantity_value / quantity_unit
availability: available | unavailable | constrained | unknown
source_type: direct | forwarded | hearsay | opinion
confidence
evidence_message_ids / evidence_text
```

`price_type` distinguishes absolute prices, percentage discounts, ranges, upper/lower bounds, and unknown semantics. Raw values are always retained beside normalized values.

## 4. Architecture and Data Flow

```text
JSONL replay or platform adapter
        -> canonical RawMessage
        -> context resolver
        -> candidate/message filtering
        -> OpenRouter extraction with abstention
        -> schema validation
        -> entity and unit normalization
        -> signal lifecycle + provenance + deduplication
        -> compatible-signal aggregation
        -> SQLite state + snapshot.json
        -> Streamlit HTML report with periodic refresh
```

Platform ingestion is separated from intelligence. Telegram, WeChat, and a replay file should emit the same `RawMessage` contract. The timeboxed baseline uses a replay file; live platform adapters remain optional.

The raw message stream is append-only. Derived contexts, signals, lifecycle transitions, and snapshots can be recomputed from it. This keeps the design auditable and makes prompt/model changes replayable.

The LLM interprets language. Deterministic components protect data integrity: they decide whether values are comparable, whether a forwarded message is independent supply, whether a signal is expired, and how statistics are calculated.

### Recommended local prototype stack

- **Input fixture:** newline-delimited JSON at `data/chat_messages.jsonl`, containing canonical `RawMessage` records. It includes normal, duplicate, delayed, forwarded, out-of-order, correction, and reply cases.
- **Replay producer:** Python producer with `speed=0` for deterministic evaluation, accelerated playback for demos, and optional real-time-like playback.
- **Event channel:** in-process `asyncio.Queue[RawMessage]`, demonstrating producer/consumer boundaries without adding a service.
- **State and evidence:** SQLite for message metadata, contexts, signals, lifecycle transitions, and provenance. JSONL remains the portable input/output format.
- **Processing:** Python and Pydantic for contracts; deterministic modules for context, normalization, deduplication, and aggregation.
- **LLM:** OpenRouter through a provider adapter; the model is configurable and isolated from the rest of the pipeline.
- **Presentation:** Streamlit serves the HTML report and periodically reruns the snapshot query. The report layer does not own ingestion or extraction.

The simulator keeps `event_time` separate from `ingested_at` and supports bounded late-arrival and duplicate modes. The same input can therefore test idempotency and out-of-order handling.

### Streamlit report and refresh model

The consumer writes the latest derived snapshot to SQLite and/or an atomically replaced `snapshot.json`. Streamlit reads the snapshot on a fixed interval and re-renders tables and charts. A refresh must not trigger ingestion or re-run extraction for unchanged messages.

The report shows:

- current supply and demand by canonical resource;
- median price, observed range, dispersion, and sample counts where units are comparable;
- independent offer count and confidence;
- freshness and last-updated time;
- evidence messages behind each result.

The snapshot includes a version or `last_processed_message_id`, so the report can show whether data changed since the previous refresh.

### LLM provider boundary

The extractor uses OpenRouter through a provider adapter. The adapter owns the configurable model name, timeout, retry policy, structured-output request, token/cost metadata, and provider error classification. The rest of the pipeline depends on an `Extractor` contract rather than OpenRouter response objects.

A fake or recorded extractor is supported for deterministic evaluation and report demos without live LLM calls.

## 5. Context Resolution

Context is resolved with explicit precedence:

1. If `reply_to` is available, follow the reply chain and include the minimum relevant ancestors.
2. Otherwise, use the same group/channel and a bounded time window.
3. Add recent messages from the same author only when needed to resolve a correction or omitted entity.
4. Do not merge unrelated conversations merely because the author is the same.

For the simulated stream, a context is flushed after two minutes of inactivity in the same group, or earlier when a reply thread is closed. A late correction creates a new revision and supersedes the prior signal rather than creating a second live offer.

Each context records its boundary, included message IDs, and `context_confidence`. An incomplete reply chain lowers confidence.

## 6. Extraction Contract

The LLM handles semantic interpretation that is difficult to encode with rules: implicit references, bundled signals, corrections, slang, and transaction language. Deterministic logic handles validation, known unit parsing, canonicalization, deduplication, freshness, and aggregation.

The extractor must:

- return zero or more signals;
- use `null` or `unknown` when evidence is insufficient;
- never infer currency, unit, or completion status from a bare number;
- attach evidence message IDs and a short rationale;
- distinguish direct offers from forwarded or hearsay statements;
- support partial extraction when one part of a bundled message is ambiguous.

Invalid output, timeout, or provider failure is an extraction failure with a recorded reason, not an empty market result. Failed records remain available for retry and evaluation.

## 7. Normalization and Entity Handling

Normalization maps aliases to a versioned canonical resource ontology while retaining original text and mapping confidence. Unknown resources are stored as `unknown:<normalized_raw_text>` until the ontology is updated.

Numeric normalization is allowed only when the dimension is known. `8-card A100` can become quantity `8` with unit `gpu` if supported by the domain dictionary. `30% off` remains a discount, not a dollar price. Incompatible currencies and units are never combined in one aggregate.

## 8. Signal Lifecycle, Provenance, and Deduplication

The system distinguishes:

- repeated ingestion of the same message;
- repeated messages from the same source;
- independent messages referring to the same underlying offer.

Every signal keeps message IDs, group, user, event time, raw evidence, source type, and an `offer_id` when an offer cluster can be inferred. A content fingerprint is only one input to deduplication; time, source lineage, forwarding metadata, normalized resource, quantity, and price semantics also matter.

Message processing is idempotent on `message_id`. Signal revisions use a stable logical key plus revision number. Signals have this lifecycle:

```text
observed -> corrected | superseded | disputed | expired
```

The aggregation layer counts independent observations by source/offer clusters, not raw message count. Forwarded broker spam therefore does not automatically look like new supply.

## 9. Aggregation and Snapshot Contract

Market snapshots are grouped by:

```text
resource_id + signal_kind + direction + price_type + currency + price_unit + time_bucket
```

The snapshot contains:

```json
{
  "version": 42,
  "generated_at": "...",
  "last_event_time": "...",
  "last_processed_message_id": "m-128",
  "rows": [],
  "pipeline_errors": []
}
```

Each row should expose, where available:

- supply volume and demand volume;
- median price, p25, p75, and observed range;
- availability state;
- sample count and independent offer count;
- freshness and confidence.

Confidence is reported separately from price. It should not hide disagreement through an opaque confidence-weighted average. Historical, expired, or incompatible-unit signals are excluded from the current snapshot but remain queryable as evidence.

## 10. Evaluation Plan

The evaluation set contains at least 20 hand-labeled clean and adversarial cases: corrections, missing units, aliases, bundled offers, replies, forwarded quotes, historical references, contradictory quotes, incomplete context, and irrelevant chatter.

Evaluation is split into layers:

- signal kind and direction accuracy;
- resource normalization accuracy;
- price and quantity semantic accuracy;
- thread linking and correction resolution;
- duplicate and independent-offer precision/recall;
- confidence calibration;
- aggregation sanity checks for supply/demand, freshness, and incompatible units.

Each case stores expected outputs, evidence references, and acceptable uncertainty. The evaluation output reports false positives separately from unresolved or abstained cases.

## 11. Security and Operational Boundaries

Chat text is untrusted input and must be delimited when sent to the LLM. User IDs are anonymized in the Streamlit report by default. OpenRouter credentials are read from environment variables and never written to message fixtures or snapshots. Provider errors, retries, model version, and prompt version are recorded for diagnosis.

## 12. Known Failure Modes and Trade-offs

- Ambiguous units or currencies may remain unresolved; preserving uncertainty is preferable to false precision.
- Different users may intentionally quote the same offer; offer clustering can be uncertain and should expose provenance.
- A reply chain may be incomplete; the context resolver lowers confidence when ancestors are missing.
- LLM output can be invalid, delayed, or inconsistent across model versions; validation and bounded retries are required.
- Larger contexts improve interpretation but add latency and token cost; bounded windows and caching are appropriate.
- Availability opinions can be useful but should not be mixed with concrete inventory volume.

## 13. Prioritization

The required design centers on the message contract, signal semantics, context rules, normalization, provenance, aggregation, evaluation, and the Streamlit snapshot contract. A replayed local stream is sufficient to demonstrate the design.

Optional extensions include live Telegram ingestion, multilingual extraction, ontology search, anomaly detection, cost-aware model routing, custom frontend work, and Kafka/Flink integration. They should be added only after the core signal model and evaluation are stable.
