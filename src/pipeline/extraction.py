"""
Stage 3: Extraction
Calls OpenRouter LLM to extract structured MarketSignals from a context block.

Primary model:  google/gemini-2.5-flash  (fast, cheap, good at structured output)
Fallback model: google/gemini-2.5-pro    (used when flash returns low-confidence results)
"""
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from typing import List
from src.models import ExtractionResult, MarketSignal, RawMessage

load_dotenv()

# ── OpenRouter client (OpenAI-compatible) ────────────────────────────────────
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

PRIMARY_MODEL = "google/gemini-2.5-flash"
FALLBACK_MODEL = "google/gemini-2.5-pro"
CONFIDENCE_THRESHOLD = 0.5   # retry with pro if avg confidence below this

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://chumi-task.local",
    "X-Title": "Market Signal Bot",
}

# ── Prompt template ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a market intelligence AI specializing in informal AI resource trading groups (Telegram, WeChat).
Your job is to extract structured market signals from raw chat messages.

Resources include: API credits (OpenAI, Claude/Anthropic, Gemini/Google), GPU compute (A100, H100, AWS, GCP), 
AI tool subscriptions (Midjourney, Cursor, etc.), and AI accounts/access.

Rules:
- A single message can produce MULTIPLE signals (e.g. bundled offer).
- Multiple messages can produce ONE signal (e.g. self-correction, reply thread).
- If a user corrects themselves, output only the FINAL corrected value.
- If a message is casual chatter, historical reference, or complaint with no active trade intent, use intent=irrelevant or observation_past.
- Never invent units or prices. If ambiguous, preserve raw string and lower confidence_score.
- For completed transactions (e.g. "Deal, PM me"), use intent=transaction_completed.
- Always include source_msg_ids for every signal produced.
- Return valid JSON matching the schema exactly."""

def build_user_prompt(context_text: str, msg_ids: List[str]) -> str:
    return f"""Analyze the following chat context and extract all market signals.

Chat context:
{context_text}

Message IDs in this context: {msg_ids}

Return a JSON object with a single key "signals" containing a list of MarketSignal objects.
Each MarketSignal must have:
- resource_entity: canonical name (e.g. "Claude_API", "OpenAI_Credits", "AWS_Compute", "H100_GPU", "Midjourney_Sub", "Cursor_Sub", "Gemini_API")
- intent: one of "buy", "sell", "inquiry", "observation_past", "irrelevant", "transaction_completed"
- price: float or null
- raw_price_str: original price text or null
- volume: float or null  
- raw_volume_str: original volume text or null
- confidence_score: 0.0-1.0
- explanation: brief reasoning
- source_msg_ids: list of message IDs that produced this signal

If there are no actionable signals, return {{"signals": []}}."""


def call_openrouter(context_text: str, msg_ids: List[str], model: str) -> ExtractionResult:
    """Call OpenRouter with the given model and return parsed ExtractionResult."""
    user_prompt = build_user_prompt(context_text, msg_ids)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        extra_headers=OPENROUTER_HEADERS,
    )
    
    content = response.choices[0].message.content
    data = json.loads(content)
    
    # Handle case where LLM wraps signals differently
    if "signals" not in data:
        # Try to find a list at top level
        for v in data.values():
            if isinstance(v, list):
                data = {"signals": v}
                break
        else:
            data = {"signals": []}
    
    return ExtractionResult(**data)


def extract_signals(context: List[RawMessage], context_text: str) -> List[MarketSignal]:
    """
    Extract market signals from a context block.
    
    Uses flash as primary. If average confidence is below threshold, 
    retries with pro (cost-aware model routing).
    """
    msg_ids = [m.msg_id for m in context]
    
    try:
        result = call_openrouter(context_text, msg_ids, PRIMARY_MODEL)
    except Exception as e:
        print(f"  [Extraction] Flash failed ({e}), trying Pro fallback...")
        try:
            result = call_openrouter(context_text, msg_ids, FALLBACK_MODEL)
        except Exception as e2:
            print(f"  [Extraction] Pro also failed ({e2}). Skipping context.")
            return []

    signals = result.signals

    # Cost-aware routing: if flash returns low confidence, retry with pro
    if signals:
        avg_confidence = sum(s.confidence_score for s in signals) / len(signals)
        if avg_confidence < CONFIDENCE_THRESHOLD:
            print(f"  [Extraction] Low confidence ({avg_confidence:.2f}), retrying with Pro...")
            try:
                pro_result = call_openrouter(context_text, msg_ids, FALLBACK_MODEL)
                if pro_result.signals:
                    signals = pro_result.signals
            except Exception as e:
                print(f"  [Extraction] Pro retry failed ({e}), keeping flash result.")

    return signals
