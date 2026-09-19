# Adversarial Use Cases and Handling Strategies

These cases define the semantic behavior expected from the market-signal design. They are also the seed for a small hand-labeled evaluation set. The expected result is a signal plus evidence and uncertainty, not merely a guessed price.

## Case 1: Self-correction

**Input stream**

- `[10:00] User A:` “Selling Claude API, 4.0 per unit.”
- `[10:01] User A:` “Typo, meant 3.8.”

**Challenge**

The second message omits the resource and changes the prior value. Parsing it alone loses the entity; treating both messages as live offers double-counts supply.

**Handling**

The context resolver includes both messages. The second message creates a correction edge and supersedes the first signal. The resulting signal keeps both message IDs as evidence and reports the latest price as `3.8` with the original unit still marked as unknown if it was never defined.

## Case 2: Missing units and industry slang

**Input stream**

- `[11:00] User B:` “Still looking for 500k OpenAI, below 4 if possible.”
- `[11:05] User C:` “Got 8-card A100s, spot.”

**Challenge**

`500k` may be tokens, dollars, or another quota dimension. `4` has no currency or price unit. `8-card` is domain slang for an eight-GPU offer but should not be assumed outside a supported dictionary.

**Handling**

The first message becomes a demand signal with `quantity_value=500000`, `quantity_unit=unknown`, and an upper-bound price with unknown currency. The second becomes a supply signal with quantity `8` and unit `gpu` only if the domain dictionary recognizes the phrase. Unknown dimensions are preserved and excluded from incompatible price aggregates.

## Case 3: Forwarded duplicate offer and provenance

**Input stream**

- `[Group 1] [12:00] Broker X:` “Discounted Midjourney annual subs, $150 each.”
- `[Group 2] [12:05] Broker X:` “Discounted Midjourney annual subs, $150 each.”
- `[Group 3] [12:10] Broker Y (forwarding):` “Discounted Midjourney annual subs, $150 each.”

**Challenge**

Three messages do not necessarily represent three independent offers.

**Handling**

Message deduplication, repeated-source detection, and offer-level clustering are separate steps. The system preserves all three messages, records forwarding/source lineage, and may assign them to one `offer_id`. The snapshot reports raw mentions and independent offer clusters separately.

## Case 4: Historical reference and current availability observation

**Input stream**

- `[13:00] User D:` “Remember when OpenAI was going for 2.0? Crazy times.”
- `[13:02] User E:` “The 3.8 seller from yesterday is completely ignoring me.”
- `[13:05] User F:` “AWS is being so strict with quotas lately.”

**Challenge**

The first two messages refer to past or stale events. The third contains no concrete offer but may be a useful current availability observation.

**Handling**

The first two signals receive `temporal_status=historical` and do not enter the current snapshot. The third becomes an `availability` observation with `availability=constrained`, low-to-medium confidence, and no fabricated price or volume.

## Case 5: Bundled offers

**Input stream**

- `[14:00] User G:` “Got 2 AWS $100k accounts at 30% off, and throwing in a GCP $50k account for 25% off.”

**Challenge**

A single message contains multiple resources, quantities, quota dimensions, and discount semantics.

**Handling**

The extractor returns two signals. Each signal keeps the raw quota amount and represents `30% off` or `25% off` as `price_type=percentage_discount`; neither is converted into an absolute price. The two signals share the same evidence message but have separate resource IDs and quantities.

## Case 6: Multi-party negotiation thread

**Input stream**

- `[Msg 1] User H:` “Need $120 OpenAI accounts.”
- `[Msg 2] User I (replying to 1):` “I have 5. Standard rate?”
- `[Msg 3] User H (replying to 2):` “Deal, PM me.”

**Challenge**

The final message is unintelligible without the thread. It signals commitment, but does not independently prove settlement or delivery.

**Handling**

The thread resolver follows `reply_to` links. The system produces a demand signal and a supply signal, links them to one negotiation context, and marks the transaction state as `commitment` unless there is explicit completion evidence. The agreed price and quantity retain their evidence references.

## Case 7: Contradictory quotes

**Input stream**

- `[15:00] User J:` “Claude API is 3.8 today.”
- `[15:02] User K:` “No, I can get it at 4.2.”

**Challenge**

The messages may describe different units, sources, or market conditions. Choosing one value silently would hide disagreement.

**Handling**

Both current price observations are retained with source and unit metadata. The snapshot exposes median and dispersion only when the price semantics are compatible, and keeps the observed range and sample count visible.

## Case 8: Alias and unknown resource

**Input stream**

- `[16:00] User L:` “Sonnet quota available.”
- `[16:01] User M:` “Claude 3.5 API still has stock.”
- `[16:02] User N:` “New model X access, 20 slots.”

**Challenge**

The first two messages may refer to the same canonical resource. The third is a new resource that is not in the ontology.

**Handling**

The alias layer maps known aliases to a versioned canonical resource with a mapping confidence. The unknown resource is retained as `unknown:<normalized_raw_text>` and remains queryable until the ontology is updated.

## Case 9: Irrelevant numeric chatter

**Input stream**

- `[17:00] User O:` “The model had 2 million downloads last month.”
- `[17:01] User P:` “AWS was founded in 2006.”

**Challenge**

Numbers and resource names do not automatically indicate supply, demand, price, or availability.

**Handling**

The messages are classified as `irrelevant` or `opinion` and produce no current market signal. Their classification remains available for evaluation so false positives can be measured.

## Case 10: Missing context or incomplete reply chain

**Input stream**

- `[18:00] User Q:` “Yes, I can take 200 at 3.8.”

**Challenge**

The referenced resource, currency, and direction are absent because the parent message was not ingested.

**Handling**

The extractor may produce a partial signal only if the available text supports it. Missing fields remain unknown, `context_confidence` is lowered, and the result is excluded from precise resource-level aggregation until a later context update resolves it.

## Evaluation labels

Each case should store expected values for resource, signal type, temporal status, transaction status, price semantics, quantity semantics, and whether the signal contributes to the current snapshot. Evidence message IDs and acceptable uncertainty ranges should also be labeled.
