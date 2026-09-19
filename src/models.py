from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalKind(str, Enum):
    OFFER = "offer"
    REQUEST = "request"
    PRICE_QUOTE = "price_quote"
    AVAILABILITY = "availability"
    TRANSACTION = "transaction"


class Direction(str, Enum):
    SUPPLY = "supply"
    DEMAND = "demand"
    UNKNOWN = "unknown"


class TemporalStatus(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    FUTURE = "future"
    UNKNOWN = "unknown"


class TransactionStatus(str, Enum):
    NONE = "none"
    INQUIRY = "inquiry"
    NEGOTIATION = "negotiation"
    COMMITMENT = "commitment"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Availability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    CONSTRAINED = "constrained"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    DIRECT = "direct"
    FORWARDED = "forwarded"
    HEARSAY = "hearsay"
    OPINION = "opinion"


class RawMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    msg_id: str
    user_id: str
    timestamp: str
    text: str
    group_id: str
    platform: str = "mock"
    reply_to: Optional[str] = None
    forwarded_from: Optional[str] = None
    ingested_at: Optional[str] = None

    @property
    def event_time(self) -> datetime:
        value = self.timestamp.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.astimezone()


class MarketSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_entity: str = Field(..., min_length=1)
    raw_resource_text: Optional[str] = None
    signal_kind: SignalKind
    direction: Direction = Direction.UNKNOWN
    temporal_status: TemporalStatus = TemporalStatus.UNKNOWN
    transaction_status: TransactionStatus = TransactionStatus.NONE
    price: Optional[float] = None
    raw_price_str: Optional[str] = None
    price_currency: Optional[str] = None
    price_unit: Optional[str] = None
    price_type: str = "unknown"
    volume: Optional[float] = None
    raw_volume_str: Optional[str] = None
    volume_unit: Optional[str] = None
    availability: Availability = Availability.UNKNOWN
    source_type: SourceType = SourceType.DIRECT
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str = ""
    source_msg_ids: List[str] = Field(default_factory=list)
    source_user_ids: List[str] = Field(default_factory=list)
    source_group_ids: List[str] = Field(default_factory=list)
    offer_id: Optional[str] = None
    lifecycle_status: str = "observed"
    revision: int = Field(default=1, ge=1)

    @field_validator("source_msg_ids", "source_user_ids", "source_group_ids", mode="before")
    @classmethod
    def ensure_list(cls, value):
        if value is None:
            return []
        return value if isinstance(value, list) else [str(value)]


class ExtractionResult(BaseModel):
    signals: List[MarketSignal] = Field(default_factory=list)


class AggregatedTrend(BaseModel):
    resource_entity: str
    supply_volume: Optional[float] = None
    demand_volume: Optional[float] = None
    supply_signals: int = 0
    demand_signals: int = 0
    median_price: Optional[float] = None
    price_p25: Optional[float] = None
    price_p75: Optional[float] = None
    price_range_min: Optional[float] = None
    price_range_max: Optional[float] = None
    sample_count: int = 0
    independent_offer_count: int = 0
    avg_confidence: float = 0.0
    availability_state: str = "unknown"
    last_updated: str
