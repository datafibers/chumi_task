# Design Notes: Market Signal Intelligence Bot

## 1. Architecture Overview
To process noisy, informal group-chat messages into actionable resource trends within the 4-8 hour timebox, the system is designed as a **real-time streaming pipeline** emphasizing context-awareness and LLM-driven semantic extraction. 

We adopted a Producer-Consumer architecture to demonstrate the "streaming ingestion" and "interactive dashboard" optional extensions:
- **Producer (`mock_producer.py`)**: Simulates live Telegram/WeChat streams by pushing adversarial chat messages into a local buffer (`data/chat_stream.jsonl`) every few seconds.
- **Consumer & UI (`dashboard.py`)**: A Streamlit application that continuously polls the buffer, processes new messages through the pipeline, and updates a live HTML dashboard.

### The Processing Pipeline (5 Stages)
1. **Ingestion Layer:** Reads the incoming message stream.
2. **Context Assembly:** Groups isolated messages into logical conversation contexts (e.g., sliding time-windows per `user_id`). This ensures the extraction layer has the necessary context to resolve ambiguities (like self-corrections).
3. **Extraction Layer (LLM via OpenRouter):** Prompts an LLM via the OpenRouter API (using `openai` Python SDK) with Structured Output to process the assembled context and extract a list of `MarketSignal` objects.
4. **Normalization & Dedup Layer (Deterministic):** Standardizes resource aliases and handles cross-batch state overwrites.
5. **Aggregation Layer:** Uses Pandas to compute live market metrics (median price, volume, confidence-weighted averages) grouped by resource type.

## 2. Tech Stack & Justifications
- **Language:** Python 3.10+ (Standard for data engineering and AI integration).
- **LLM Routing:** **OpenRouter** (via `openai` SDK). Allows seamless switching between cutting-edge models (e.g., Gemini 2.5 Flash, Claude 3.5 Sonnet) using a single, unified API interface.
- **Data Modeling:** **Pydantic**. Guarantees that the unstructured text is cast into rigid, strongly-typed `MarketSignal` schemas, preventing downstream pipeline crashes.
- **Data Aggregation:** **Pandas**. Highly optimized for grouped statistical calculations (medians, variances, unique counts) necessary for the trend views.
- **Presentation:** **Streamlit**. Chosen to fulfill the "interactive dashboard" requirement. It provides a polished, auto-refreshing HTML UI without needing a separate frontend codebase.

## 3. Core Abstractions
- **RawMessage:** Represents an incoming chat event (`msg_id`, `user_id`, `timestamp`, `text`, `reply_to`).
- **MarketSignal:** The fundamental unit of extracted intelligence:
  - `resource_entity`: Canonical name of the resource (e.g., `AWS_Compute`).
  - `intent`: Enum (`BUY`, `SELL`, `INQUIRY`, `OBSERVATION_PAST`, `IRRELEVANT`). This enum is critical for filtering out historical complaints or casual chatter.
  - `price` & `volume`: Numeric values.
  - `confidence_score`: Float indicating how certain the LLM is about the extraction.

## 4. Key Design Decisions & Trade-offs

### LLM Extraction vs. Regex/Deterministic Parsing
* **Decision:** Rely heavily on LLMs for extracting entities and intents, rather than building massive Regex rules.
* **Trade-off:** Slower processing time and higher compute cost per message, but significantly more robust against typos, slang, and evolving market terminology ("black-market jargon"). Regex fails completely on implicit context.

### Handling Corrections via Context vs. State Machine
* **Decision:** Resolve user corrections (e.g., "Wait, I meant 3.8") at the **Extraction Layer** by feeding the LLM an assembled thread of messages, rather than trying to reconcile conflicting signals purely via downstream database logic.
* **Trade-off:** Requires a stateful Ingestion/Assembly layer to buffer messages before processing. The Normalization layer acts purely as a fallback for cross-batch overwrites.

## 5. Known Failure Modes & Limitations
- **Unit Ambiguity:** The system may struggle if a price is given as "4" without context. Does it mean $4, 4 RMB, or a 40% discount? Currently, we rely on the LLM's world knowledge, which might hallucinate units if the context is completely barren.
- **Cross-User Sybil Attacks (Spam):** If multiple broker accounts forward the exact same offer, the system might count them as independent signals, artificially inflating market volume.
- **Latency vs. Context tradeoff:** Grouping messages by time windows inherently introduces processing latency before a signal appears on the dashboard.

## 6. Evaluation

Since this system does not fine-tune a model, evaluation serves three distinct purposes rather than traditional ML benchmarking:

### 6.1 Prompt Regression Suite
A small adversarial golden set of ~20 hand-crafted messages with expected `MarketSignal` outputs acts as a regression test whenever the prompt or underlying model changes. For each golden case we check:
- Was `intent` classified correctly? (e.g., `IRRELEVANT` vs `SELL`)
- Was `resource_entity` canonicalized to the right name?
- Was `confidence_score` appropriately low when units were missing?
- For self-correction cases, did the final signal reflect the corrected value, not the original?

This allows us to answer: *"Did my prompt change make things better or worse?"* and *"Does swapping from `gemini-2.5-flash` to `claude-sonnet` regress any cases?"*

### 6.2 Pipeline Unit Tests (Deterministic Layers)
The Normalization, Dedup, and Aggregation layers are pure Python and can be tested independently of the LLM with fixed inputs:
- Given a list of signals with known duplicates, verify that the dedup hash correctly collapses them.
- Given a known signal list, verify that the aggregation produces the correct median price and independent signal count.

### 6.3 Failure Mode Discovery
Running the adversarial dataset through the live pipeline and observing real LLM outputs is the highest-value evaluation step. When the system produces an unexpected result (e.g., misclassifying broker spam as a genuine `SELL` signal, or hallucinating a unit for an ambiguous price), this surfaces a new failure mode that feeds back into both the prompt and the use case documentation.

This is an **iterative loop**, not a one-shot benchmark: discover failure → document it → improve prompt → re-run golden set.

## 7. Next Steps for Production
1. **Entity Ontology Database:** Implement a vector DB or dictionary mapping layer to standardize slang (e.g., aligning "sonnet" and "claude 3.5" to the same canonical ID) before aggregation.
2. **Provenance Hashing:** Hash the core components of a signal `hash(resource, price, volume)` to deduplicate identical offers spammed across multiple groups by different broker accounts.
3. **Kafka/Flink Integration:** Replace the local `jsonl` polling with a real-time event streaming platform for horizontal scalability.
