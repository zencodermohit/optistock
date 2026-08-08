from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DailyMetric(Base):
    """One company's trading on one day.

    A projection: every column is derived from sales and inventory_movements,
    and the table can be dropped and rebuilt without losing anything. That is
    what makes it safe to keep denormalised and to change the shape of later --
    a wrong projection is a rebuild, not a data migration.

    Maintained two ways, deliberately:

    *   Incrementally, by a consumer reacting to events, so today's figures are
        current within a second of a sale.
    *   In bulk, by ``rebuild_daily_metrics``, which recomputes from the source
        tables. That is how history that predates the event system gets here,
        and how a bug in a handler stops being permanent.
    """

    __tablename__ = "daily_metrics"

    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_date = Column(Date, primary_key=True)

    revenue = Column(Numeric(14, 2), nullable=False, server_default="0")
    orders = Column(Integer, nullable=False, server_default="0")
    units_sold = Column(Integer, nullable=False, server_default="0")

    stock_movements = Column(Integer, nullable=False, server_default="0")
    units_received = Column(Integer, nullable=False, server_default="0")

    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
