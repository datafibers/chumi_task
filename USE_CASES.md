# Adversarial Use Cases & Handling Strategies

This document outlines the complex, adversarial scenarios expected in informal AI resource trading chats and how our system is designed to handle them. These examples guide the creation of our mock dataset and evaluation criteria.

## Case 1: The Self-Correction
**Input Stream:**
- `[10:00] User A:` "Selling Claude API, 4.0 per unit."
- `[10:01] User A:` "Typo, meant 3.8."

**Challenge:** The second message lacks the entity context ("Claude API"). Parsing it in isolation yields a useless signal.
**Handling Strategy:**
- **Context Assembly:** The ingestion layer groups messages by `user_id` within a small time window. Both messages are passed as a single context block to the LLM.
- **Extraction:** The LLM receives the prompt: *"Extract the final intended market signal from this user's message sequence."* It outputs a single `MarketSignal` for Claude API at 3.8, seamlessly handling the correction.

## Case 2: Missing Units & Industry Slang
**Input Stream:**
- `[11:00] User B:` "Still looking for 500k OpenAI, below 4 if possible."
- `[11:05] User C:` "Got 8-card A100s, spot."

**Challenge:** "500k" could mean tokens, dollars, or RPM. "4" could mean $4, ¥4, or a discount rate. "8-card" is slang for an 8-GPU instance.
**Handling Strategy:**
- **Extraction & Normalization:** The LLM is instructed to extract `raw_price` and `raw_volume` as strings. The Normalization layer uses a domain-specific dictionary: if the resource is `OpenAI_API`, single-digit prices are flagged. The LLM also assigns a lower `confidence_score` (e.g., 0.5) when explicit units are missing, allowing the Aggregation layer to weight these signals less heavily.

## Case 3: Duplication & Provenance (Broker Spam)
**Input Stream:**
- `[Group 1] [12:00] Broker X:` "Discounted Midjourney annual subs, $150 each."
- `[Group 2] [12:05] Broker X:` "Discounted Midjourney annual subs, $150 each."
- `[Group 3] [12:10] Broker Y (Forwarding):` "Discounted Midjourney annual subs, $150 each."

**Challenge:** Directly aggregating these results in an inflated market supply of 3 units, when there is likely only 1 underlying event/offer being spammed.
**Handling Strategy:**
- **Deduplication:** At the Normalization layer, we generate a hash for each signal: `hash(intent + resource_entity + price)`. If identical hashes occur within a 2-hour window, they are flagged as duplicates. The Aggregation layer calculates `independent_signals` by counting distinct hashes, not total raw messages.

## Case 4: Historical Context & Irrelevant Chatter
**Input Stream:**
- `[13:00] User D:` "Remember when OpenAI was going for 2.0? Crazy times."
- `[13:02] User E:` "The 3.8 seller from yesterday is completely ignoring me."
- `[13:05] User F:` "AWS is being so strict with quotas lately."

**Challenge:** These messages contain numbers and resource names but represent zero active market supply or demand.
**Handling Strategy:**
- **Intent Filtering:** The Pydantic Schema for the LLM includes intents like `OBSERVATION_PAST` and `IRRELEVANT`. The LLM classifies User D and E as `OBSERVATION_PAST` and User F as `IRRELEVANT`. The Aggregation layer strictly filters out these intents when calculating current market depth.

## Case 5: Bundled Offers (Multi-Signal Extraction)
**Input Stream:**
- `[14:00] User G:` "Got 2 AWS $100k accounts at 30% off, and throwing in a GCP $50k account for 25% off."

**Challenge:** A single message contains multiple distinct market signals across different resource types.
**Handling Strategy:**
- **Schema Design:** The LLM output schema is defined as a `List[MarketSignal]`. This forces the LLM to separate the bundled offer into two distinct JSON objects (one for AWS, one for GCP), which are then routed to their respective resource aggregation buckets.

## Case 6: Multi-party Transaction Threads (The Holy Grail)
**Input Stream:**
- `[Msg 1] User H:` "Need $120 OpenAI accounts."
- `[Msg 2] User I (replying to 1):` "I have 5. Standard rate?"
- `[Msg 3] User H (replying to 2):` "Deal, PM me."

**Challenge:** This represents a completed transaction, which is highly valuable data, but the final intent ("Deal") has no context on its own.
**Handling Strategy:**
- **Thread Assembly:** The Ingestion layer builds a conversation tree based on `reply_to` IDs. The entire thread is fed to the LLM. 
- **Intent Evolution:** The LLM can identify this as a `TRANSACTION_COMPLETED` intent, extracting the agreed price/volume from the historical context of the thread. This is a stretch goal but demonstrates the power of context-aware extraction.
