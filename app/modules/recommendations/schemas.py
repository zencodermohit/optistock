from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Dict, Any


# -----------------------------------------
# Recommendation Schemas
# -----------------------------------------
class RecommendationCreate(BaseModel):
    """Schema for creating a new recommendation (typically by an ML pipeline)."""

    # `source` is intentionally absent and extras are forbidden: a caller must
    # not be able to label their row as pipeline-generated, which would let the
    # nightly job delete it and would falsify the provenance of the feed.
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    warehouse_id: UUID
    suggested_action: str = Field(
        ...,
        min_length=2,
        max_length=50,
        description="e.g., reorder, transfer, discount",
    )
    suggested_quantity: int = Field(..., gt=0, description="How many units to act on")
    confidence_score: int = Field(
        ..., ge=1, le=100, description="ML confidence on a 1-100 scale"
    )
    evidence: Dict[str, Any] = Field(
        ...,
        description="Supporting data, e.g. {'demand_spike': '+20%', 'lead_time_risk': 'high'}",
    )
    business_reasoning: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Human-readable explanation of why this action is recommended",
    )


class RecommendationResponse(BaseModel):
    """Schema for returning a recommendation to the client."""

    id: UUID
    product_id: UUID
    warehouse_id: UUID
    suggested_action: str
    suggested_quantity: int
    confidence_score: int
    evidence: Dict[str, Any]
    business_reasoning: str
    source: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedRecommendationsResponse(BaseModel):
    """Standard paginated response envelope."""

    total: int
    skip: int
    limit: int
    data: List[RecommendationResponse]
