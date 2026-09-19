# Design Notes: Market Signal Intelligence Bot

## 1. Problem Definition

The system turns noisy group-chat messages into time-bounded market observations for AI resources such as model/API access, credits, accounts, quotas, and compute.

The unit of analysis is a **market signal**, not a message. A signal is an observation about a canonical resource, expressed by a source at a point in time, with enough evidence to explain how it was derived. A single message can produce multiple signals, and several messages can jointly produce one signal.

The system should be conservative: when price, unit, resource identity, or temporal status is unclear, it preserves the raw value and lowers confidence or abstains instead of inventing a normalization.

## 2. Design Goals and Non-goals

### Goals

- Extract supply, demand, price, availability, and transaction observations from informal messages.
- Resolve meaning that depends on replies, quoted messages, corrections, or recent conversation state.
- Preserve raw evidence and source lineage for every derived signal.
- Normalize comparable resources and units while retaining unknown/new resources.
- Produce an interpretable market snapshot with freshness and uncertainty.
- Make extraction quality measurable with a small adversarial evaluation set.

### Non-goals for the timebox

- Direct production integration with Telegram or WeChat.
- Fully automated entity ontology management.
- Treating every conversational statement as a reliable market quote.
- Building a distributed streaming platform before the signal semantics are stable.

## 3. Conceptual Data Model

The pipeline uses five explicit concepts:

1. **RawMessage**: an immutable platform event with `message_id`, `platform`, `group_id`, `user_id`, `timestamp`, `text`, `reply_to`, and forwarding metadata.
2. **Context**: the smallest set of related messages required to interpret one or more signals. Context keeps message order and records why each message was included.
3. **MarketSignal**: a structured observation derived from a context. It contains a canonical resource when known, a signal type, currentness, optional price/quantity with units, confidence, and evidence references.
4. **OfferEvent**: an inferred underlying offer or request that may be mentioned repeatedly or forwarded across groups. This is separate from the messages that mention it.
5. **MarketSnapshot**: a time-windowed aggregation of compatible signals, split by resource, direction, price semantics, and freshness.

The minimum signal dimensions are:

```text
resource_id / raw_resource_text
signal_type: supply | demand | price_quote | availability | transaction
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
Platform adapter or replay file
        -> canonical RawMessage
        -> context resolver
        -> candidate/message filtering
        -> structured extraction with abstention
        -> schema validation
        -> entity and unit normalization
        -> signal lifecycle + provenance + deduplication
        -> compatible-signal aggregation
        -> snapshot/trend view
```

Platform ingestion is intentionally separated from intelligence. Telegram, WeChat, and a replayed JSONL file should emit the same `RawMessage` contract. The timeboxed baseline can use replayed messages; live polling and a dashboard remain optional extensions.

The raw message stream is append-only. Derived contexts, signals, lifecycle transitions, and snapshots can be recomputed from it. This keeps the design auditable and makes prompt/model changes replayable. A small local store is sufficient for the timebox; a queue and separate event store are production scaling choices.

The main boundary is deliberate: the LLM interprets language, while deterministic components protect data integrity. The LLM should not decide whether two prices are numerically comparable, whether a forwarded message is independent supply, or whether an expired signal belongs in the current snapshot.

### Recommended local prototype stack

- **Input fixture:** newline-delimited JSON (`data/chat_messages.jsonl`) containing canonical `RawMessage` records. The fixture is sorted by event time but includes optional duplicate, delayed, forwarded, and out-of-order cases.
- **Replay producer:** a small Python producer that emits one message at a time. It supports `speed=0` for deterministic tests, accelerated playback for demos, and real-time-like playback for the optional dashboard.
- **Event channel:** an in-process `asyncio.Queue[RawMessage]`. This demonstrates producer/consumer boundaries without introducing Kafka or another service during the timebox.

### Main Processing Pipeline (5 Stages)

```
Raw Chat Messages
       │
       ▼
┌──────────────────────┐
│   1. Ingestion        │  Reads chat_stream.jsonl, parses RawMessage objects
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  2. Context Assembly  │  Groups messages by user_id + time_window / reply_to tree
└───────────┬──────────┘  ◄── Key layer for self-corrections & multi-turn threads
            │
            ▼
┌──────────────────────┐
│  3. Extraction (LLM)  │  Calls OpenRouter → outputs List[MarketSignal]
└───────────┬──────────┘  ◄── Semantic understanding: slang, intent, confidence
            │
            ▼
┌──────────────────────┐
│  4. Normalization     │  Alias canonicalization + hash-based dedup + state overwrite
│     & Dedup           │  ◄── Pure deterministic Python logic (no LLM)
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  5. Aggregation       │  Pandas: median price, independent signal count,
└───────────┬──────────┘          confidence-weighted averages, per resource
            │
            ▼
   Streamlit Dashboard  (live auto-refreshing HTML UI in browser)
```

### Streaming Architecture (Producer-Consumer)

To demonstrate real-time ingestion, the system is split into two independent processes:

```
mock_producer.py                   dashboard.py (Streamlit)
       │                                   │
  Writes 1 adversarial    ──────────►  Reads every 5s
  chat message every 5s    jsonl file  Runs full 5-stage pipeline
  to chat_stream.jsonl                 Updates UI in real time
```

### Layer Responsibility Summary

| Stage | Technology | Primary Responsibility |
|---|---|---|
| Ingestion | Python / jsonl | Read stream, parse, trigger grouping |
| Context Assembly | Python (dict + deque) | Build conversation context before LLM sees it |
| Extraction | OpenRouter + Pydantic | Semantic understanding → structured Signal |
| Normalization & Dedup | Python (dict + hash) | Canonicalize names, deduplicate, overwrite stale state |
| Aggregation | Pandas | Compute live market statistics |
| Dashboard | Streamlit | Real-time HTML display in browser |

The simulator should model event time separately from ingestion time. It should also support a bounded `late_arrival` and `duplicate` mode, because these cases test whether the pipeline is idempotent and whether context assembly waits for the right messages. The replay controls are part of the design: `--speed 0` is used for repeatable evaluation, while `--speed 10` or similar is used for a short demo.

### HTML report and refresh model

The consumer writes an immutable raw-event log plus the latest derived market snapshot. A small local HTTP server serves a static HTML page and a `snapshot.json` file. JavaScript fetches `snapshot.json` on a fixed interval and re-renders the tables/charts; a full-page meta refresh is a fallback for a very small demo. This avoids regenerating HTML in the processing loop and keeps the report layer independent.

- current supply and demand by canonical resource;
- median price, observed range, dispersion, and sample counts where units are comparable;
- independent offer count and confidence;
- freshness or last-updated time;
- links or expandable rows showing the evidence messages behind a result.

The refresh interval is a presentation concern. It must not trigger duplicate ingestion or re-run extraction for unchanged messages. The snapshot is written atomically, and a snapshot version or `last_processed_message_id` lets the report show whether data changed since the previous refresh.

### LLM provider boundary

The production-shaped extractor uses OpenRouter through a provider adapter. The adapter owns the model name, request timeout, retry policy, structured-output request, token/cost metadata, and provider error classification. The rest of the pipeline depends on an `Extractor` contract and does not depend on OpenRouter-specific response objects. A fake or recorded extractor can be used for deterministic evaluation and for report demos without making live LLM calls.

## 5. Context Resolution

Context is resolved with explicit precedence:

1. If `reply_to` is available, follow the reply chain and include the minimum relevant ancestors.
2. Otherwise, use the same group/channel and a bounded time window.
3. Add recent messages from the same author only when they are needed to resolve a correction or omitted entity.
4. Do not merge unrelated conversations merely because the author is the same.

Each context records its boundary and a `context_confidence`. A correction should supersede the prior observation when the language clearly indicates a correction; it should not create two independent live offers.

## 6. Extraction Contract

The LLM is responsible for semantic interpretation that is difficult to encode with rules: intent, implicit references, bundled signals, corrections, and informal terminology. Deterministic logic is responsible for validation, unit parsing where rules are known, canonicalization, deduplication, freshness, and aggregation.

The extractor must:

- return zero or more signals;
- use `null` or an explicit `unknown` value when evidence is insufficient;
- never infer currency, unit, or completion status solely from a bare number;
- attach evidence message IDs and a short rationale;
- distinguish direct offers from forwarded or hearsay statements;
- support partial extraction when one part of a bundled message is ambiguous.

Invalid output, timeout, or provider failure is an extraction failure with a recorded reason, not an empty market result. Failed records remain available for retry and evaluation.

## 7. Normalization and Entity Handling

Normalization maps aliases to a versioned canonical resource ontology. It should support aliases such as `sonnet` and `Claude 3.5` while retaining the original text and the mapping confidence.

Unknown resources are first-class values. They are stored as `unknown:<normalized_raw_text>` until a later ontology update; they are not silently dropped or forced into an unrelated entity.

Numeric normalization is allowed only when the dimension is known. For example, `8-card A100` can become a quantity of `8` with unit `gpu` if the phrase is supported by the domain dictionary. `30% off` remains a discount, not a dollar price. Values with incompatible currency or units are never combined in one aggregate.

## 8. Signal Lifecycle, Provenance, and Deduplication

The system distinguishes three kinds of duplication:

- repeated ingestion of the same message;
- repeated messages from the same source;
- independent messages that refer to the same underlying offer.

Every signal keeps `message_ids`, `group_id`, `user_id`, timestamp, raw evidence, source type, and an `offer_id` when an offer cluster can be inferred. A content fingerprint is only one input to deduplication; time, source lineage, forwarding metadata, normalized resource, quantity, and price semantics also matter.

Signals have a lifecycle:

```text
observed -> corrected | superseded | disputed | expired
```

The aggregation layer counts independent observations by source/offer clusters, not by raw message count. This prevents forwarded broker spam from looking like new supply while preserving provenance for review.

## 9. Aggregation Semantics

Market snapshots are grouped by:

```text
resource_id + signal_type + price_type + currency + price_unit + time_bucket
```

Supply and demand are reported separately. A snapshot should expose, where available:

- supply volume and demand volume;
- median price and observed range;
- dispersion such as IQR;
- current availability state;
- sample count and independent signal count;
- freshness and confidence.

Confidence weighting is used to communicate uncertainty, not to hide disagreement. A high-confidence outlier remains visible through range and dispersion. Historical, expired, or incompatible-unit signals are excluded from the current snapshot but remain queryable as evidence.

## 10. Evaluation Plan

The evaluation set is a small hand-labeled collection containing clean cases and adversarial cases: corrections, missing units, aliases, bundled offers, replies, forwarded quotes, historical references, contradictory quotes, and irrelevant chatter.

Evaluation is split into layers:

- extraction: resource, signal type, price/quantity semantics;
- context: thread linking and correction resolution;
- normalization: canonical entity and unit accuracy;
- deduplication: duplicate precision/recall and independent-offer accuracy;
- calibration: whether low-confidence outputs are actually less reliable;
- aggregation: supply/demand separation, freshness, and snapshot sanity checks.

The dataset stores expected outputs and evidence references, not only a final dashboard number. This makes failures diagnosable.

## 11. Known Failure Modes and Trade-offs

- Ambiguous units or currencies may remain unresolved; preserving uncertainty is preferable to false precision.
- Different users may intentionally quote the same offer; offer clustering can be uncertain and should expose provenance.
- A reply chain may be incomplete; the context resolver should lower confidence when ancestors are missing.
- LLM output can be invalid, delayed, or inconsistent across model versions; validation, retries, and model/version metadata are required.
- Context windows improve interpretation but add latency and token cost; bounded windows and caching are appropriate.
- Availability opinions such as “AWS is harder this week” can be useful but should not be mixed with concrete inventory volume.
- Chat text is untrusted input; the extractor must treat it as data and preserve delimiters around it.

## 12. Prioritization

The required design centers on the message contract, signal semantics, context rules, normalization, provenance, aggregation, and evaluation. A replayed local stream is sufficient to demonstrate the design.

Optional extensions include live Telegram ingestion, a Streamlit dashboard, multilingual extraction, ontology search, incremental aggregation, anomaly detection, cost-aware model routing, and Kafka/Flink integration. They should be added only after the core signal model and evaluation are stable.
