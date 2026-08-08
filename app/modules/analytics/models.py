import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ForecastRun(Base):
    """One stored prediction, so it can be scored against reality later.

    Without this table a forecast is an assertion. With it, accuracy becomes
    measurable: once ``horizon_end`` has passed, the actual demand over that
    window is filled in and the error recorded. Aggregating those errors gives
    MAPE — the difference between "I built a forecasting feature" and "my
    forecast is accurate to within X%, and here is the chart".
    """

    __tablename__ = "forecast_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    # --- what was predicted ---
    horizon_days = Column(Integer, nullable=False)
    forecast_quantity = Column(Integer, nullable=False)
    avg_daily_sales = Column(Numeric(12, 4), nullable=False)
    confidence_score = Column(Integer, nullable=False)
    predicted_at = Column(DateTime(timezone=True), nullable=False)
    # The date the forecast window closes. Nothing to compare against until then.
    horizon_end = Column(Date, nullable=False)

    # --- what actually happened (filled in after horizon_end) ---
    actual_quantity = Column(Integer, nullable=True)
    absolute_error = Column(Integer, nullable=True)
    scored_at = Column(DateTime(timezone=True), nullable=True)
