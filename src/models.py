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

class MarketSignal(BaseModel):
    resource_entity: str = Field(..., description="Canonical name of the resource, e.g., 'Claude_API', 'OpenAI_Credits', 'AWS_Compute'")
    intent: Intent = Field(..., description="The intent of the message related to the resource.")
    price: Optional[float] = Field(None, description="The extracted price as a float. If missing, leave as null.")
    volume: Optional[float] = Field(None, description="The extracted quantity/volume as a float. If missing, leave as null.")
    confidence_score: float = Field(..., description="0.0 to 1.0 indicating how confident you are in this extraction. Lower if units are missing.")
    explanation: str = Field(..., description="Brief explanation of why this signal was extracted.")

class ExtractionResult(BaseModel):
    signals: List[MarketSignal] = Field(..., description="List of all market signals found in the provided context.")
