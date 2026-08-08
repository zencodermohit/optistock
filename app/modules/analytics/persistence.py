"""Writes analytics output back into PostgreSQL.

This module is the wire that was missing. ``run_abc_analysis`` and
``run_demand_forecast`` both produced correct DataFrames that were then thrown
away — nothing in the application ever called them, and nothing persisted their
results. Everything here is tenant-scoped: a row is only written after the
target product/warehouse is confirmed to belong to the company_id on that row.

Both functions stage their work with flush() and never commit, following the
same transaction-boundary rule as InventoryService: the caller owns the commit.
"""

import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.modules.products.models import Product
from app.modules.recommendations.models import Recommendation
from app.modules.warehouses.models import Warehouse

logger = logging.getLogger(__name__)

PIPELINE_SOURCE = "forecast_pipeline"


def persist_abc_classes(db: Session, abc_df: pd.DataFrame) -> int:
    """Write each product's ABC class onto the product row. Returns rows updated."""
    if abc_df.empty:
        return 0

    calculated_at = datetime.now(timezone.utc)
    updated = 0

    for row in abc_df.itertuples(index=False):
        product = (
            db.query(Product)
            .filter(
                Product.id == row.product_id,
                # Tenant guard: the fact table holds every tenant's rows, so a
                # mismatch here would write one company's analysis onto another's
                # catalogue.
                Product.company_id == row.company_id,
            )
            .first()
        )
        if product is None:
            continue

        product.abc_class = row.abc_class
        product.abc_calculated_at = calculated_at
        updated += 1

    db.flush()
    logger.info(f"[ANALYTICS] Persisted ABC class for {updated} products.")
    return updated


def _on_hand(db: Session, product_id, warehouse_id) -> int:
    from app.modules.inventory.models import Inventory

    quantity = (
        db.query(Inventory.quantity)
        .filter(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        .scalar()
    )
    return int(quantity or 0)


def persist_reorder_recommendations(db: Session, forecast_df: pd.DataFrame) -> int:
    """Turn a forecast into reorder recommendations. Returns rows created.

    Recommendations are net of stock already on hand: suggesting a reorder for a
    product that is comfortably stocked is noise, and noise is how a
    recommendations feed gets ignored.

    Re-running replaces this pipeline's previous output for the same
    product/warehouse rather than appending, so the nightly job is idempotent and
    yesterday's stale numbers do not pile up. Manually created recommendations
    carry a different `source` and are never touched.
    """
    if forecast_df.empty:
        return 0

    created = 0

    for row in forecast_df.itertuples(index=False):
        product = (
            db.query(Product)
            .filter(Product.id == row.product_id, Product.company_id == row.company_id)
            .first()
        )
        warehouse = (
            db.query(Warehouse)
            .filter(
                Warehouse.id == row.warehouse_id,
                Warehouse.company_id == row.company_id,
            )
            .first()
        )
        if product is None or warehouse is None:
            logger.warning(
                "[ANALYTICS] Skipping forecast row with a cross-tenant or unknown "
                f"reference (product={row.product_id}, warehouse={row.warehouse_id})."
            )
            continue

        # Clear this pipeline's previous suggestion for the pair.
        db.query(Recommendation).filter(
            Recommendation.product_id == row.product_id,
            Recommendation.warehouse_id == row.warehouse_id,
            Recommendation.source == PIPELINE_SOURCE,
        ).delete(synchronize_session=False)

        on_hand = _on_hand(db, row.product_id, row.warehouse_id)
        shortfall = int(row.forecast_quantity) - on_hand
        if shortfall <= 0:
            continue

        evidence = {
            "units_sold_in_window": int(row.units_sold_in_window),
            "active_days": int(row.active_days),
            "avg_daily_sales": round(float(row.avg_daily_sales), 3),
            "forecast_quantity": int(row.forecast_quantity),
            "quantity_on_hand": on_hand,
            # Named to make clear this is a data-density score, not a model
            # probability. See analytics/forecast.py::_confidence.
            "confidence_basis": "share of days in the window with recorded sales",
        }

        reasoning = (
            f"Sold {evidence['units_sold_in_window']} units on "
            f"{evidence['active_days']} days, an average of "
            f"{evidence['avg_daily_sales']} units/day. Forecast demand is "
            f"{evidence['forecast_quantity']} units against {on_hand} on hand, "
            f"leaving a shortfall of {shortfall}."
        )[:500]

        db.add(
            Recommendation(
                product_id=row.product_id,
                warehouse_id=row.warehouse_id,
                suggested_action="reorder",
                suggested_quantity=shortfall,
                confidence_score=int(row.confidence_score),
                evidence=evidence,
                business_reasoning=reasoning,
                source=PIPELINE_SOURCE,
            )
        )
        created += 1

    db.flush()
    logger.info(f"[ANALYTICS] Persisted {created} reorder recommendations.")
    return created
