from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class Intent(str, Enum):
    BUY = "buy"
    SELL = "sell"
    INQUIRY = "inquiry"
    OBSERVATION_PAST = "observation_past"
    IRRELEVANT = "irrelevant"
    TRANSACTION_COMPLETED = "transaction_completed"


class RawMessage(BaseModel):
    msg_id: str
    user_id: str
    timestamp: str
    text: str
    reply_to: Optional[str] = None
    group_id: str


class MarketSignal(BaseModel):
    resource_entity: str = Field(
        ...,
        description="Canonical name of the resource, e.g. 'Claude_API', 'OpenAI_Credits', 'AWS_Compute', 'Midjourney_Sub', 'H100_GPU'"
    )
    intent: Intent = Field(
        ...,
        description="The intent: buy/sell/inquiry/observation_past/irrelevant/transaction_completed"
    )
    price: Optional[float] = Field(
        None,
        description="Normalized price as float. Null if missing or ambiguous."
    )
    raw_price_str: Optional[str] = Field(
        None,
        description="Original raw price string as it appeared in the message, e.g. '3.8', '30% off', 'below 4'."
    )
    volume: Optional[float] = Field(
        None,
        description="Quantity/volume as float. Null if missing."
    )
    raw_volume_str: Optional[str] = Field(
        None,
        description="Original raw volume string, e.g. '500k', '8-card', '100k'."
    )
    confidence_score: float = Field(
        ...,
        description="0.0 to 1.0. Lower when units/price/resource are ambiguous or missing."
    )
    explanation: str = Field(
        ...,
        description="Brief explanation of why this signal was extracted and any assumptions made."
    )
    source_msg_ids: List[str] = Field(
        default_factory=list,
        description="Message IDs that contributed to this signal (for provenance)."
    )


class ExtractionResult(BaseModel):
    signals: List[MarketSignal] = Field(
        ...,
        description="All market signals extracted from the context. Empty list if no actionable signals found."
    )


class AggregatedTrend(BaseModel):
    resource_entity: str
    sell_count: int
    buy_count: int
    median_price: Optional[float]
    price_range_min: Optional[float]
    price_range_max: Optional[float]
    total_volume: Optional[float]
    independent_signals: int
    avg_confidence: float
    last_updated: str
