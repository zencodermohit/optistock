"""Every SKU, classified by how it is behaving.

Analytics answers how the business is doing. Inventory answers where the stock
physically is. This answers the third question — how is each PRODUCT doing, and
what should somebody do about it — which is a different question from both and
was previously answered by a paginated table and a search box.

The whole page rests on one classification. Each product lands in exactly one
bucket, and the order below is the priority, because a product can honestly be
several of these at once:

    critical     selling, and nothing on any shelf. Losing sales right now.
    at_risk      under two weeks of cover at the current rate.
    dead         nothing sold in DEAD_DAYS. Capital standing still.
    overstocked  more cover than anyone needs. Capital standing still slowly.
    growing      demand up meaningfully on the previous window.
    healthy      none of the above.

Priority is by urgency and then by cost. A product that is both out of stock and
growing is reported as critical, because the growth is the reason the stockout
matters rather than a separate finding.

Everything here is measured. There is no lifecycle flag on Product and none is
invented — "dead" means no sales row exists in the window, which is the only
honest way to know it.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.sales.models import Sale, SaleItem
from app.modules.warehouses.models import Warehouse

#: No sale in this long and the stock is dead capital. Matches the Analytics
#: definition deliberately: two screens using different windows would report
#: two different answers to the same question.
DEAD_DAYS = 60

#: More cover than this and it is money on a shelf rather than stock.
OVERSTOCK_COVER_DAYS = 180

#: Under this many days of cover, somebody needs to order.
AT_RISK_COVER_DAYS = 14

#: Demand up by more than this against the previous window counts as growth.
#: Below it is noise: weekly rhythm alone moves a small SKU by ten per cent.
GROWTH_THRESHOLD = 0.20

BUCKETS = ["critical", "at_risk", "dead", "overstocked", "growing", "healthy"]


def _classify(
    on_hand: int,
    daily_rate: float,
    days_since_sale: Optional[int],
    growth: Optional[float],
) -> str:
    """One bucket per product, in priority order. See the module docstring."""
    if daily_rate > 0 and on_hand <= 0:
        return "critical"

    cover = (on_hand / daily_rate) if daily_rate > 0 else None

    if cover is not None and cover <= AT_RISK_COVER_DAYS:
        return "at_risk"
    if days_since_sale is None or days_since_sale >= DEAD_DAYS:
        # Never sold, or not for two months. Only counts when there is stock
        # to be tied up -- a discontinued line at zero costs nothing.
        return "dead" if on_hand > 0 else "healthy"
    if cover is not None and cover > OVERSTOCK_COVER_DAYS:
        return "overstocked"
    if growth is not None and growth >= GROWTH_THRESHOLD:
        return "growing"
    return "healthy"


def product_intelligence(
    db: Session,
    company_id: UUID,
    days: int = 30,
    workspace_key: Optional[str] = None,
) -> Dict[str, Any]:
    """The whole catalogue classified, optionally narrowed to one workspace.

    The KPIs, the distribution and the workspace cards are identical either
    way -- they describe the catalogue, and a page showing one group still
    needs to say how big that group is against the whole. Only the `products`
    list changes, which is what makes this one endpoint rather than two that
    can disagree.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    prior_start = now - timedelta(days=days * 2)

    products = db.query(Product).filter(Product.company_id == company_id).all()
    if not products:
        return {"kpis": {}, "distribution": [], "workspaces": [], "products": []}

    # Stock across every warehouse, per product.
    stock = {}
    for row in (
        db.query(
            Inventory.product_id,
            func.coalesce(func.sum(Inventory.quantity), 0).label("units"),
            func.count(Inventory.id).label("sites"),
        )
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .filter(Warehouse.company_id == company_id)
        .group_by(Inventory.product_id)
        .all()
    ):
        stock[row.product_id] = (int(row.units), int(row.sites))

    def sold_between(start, end):
        return {
            row.product_id: (int(row.units or 0), float(row.revenue or 0))
            for row in db.query(
                SaleItem.product_id,
                func.sum(SaleItem.quantity).label("units"),
                func.sum(SaleItem.quantity * SaleItem.unit_price).label("revenue"),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(
                Sale.company_id == company_id,
                Sale.created_at >= start,
                Sale.created_at < end,
            )
            .group_by(SaleItem.product_id)
            .all()
        }

    current = sold_between(window_start, now)
    previous = sold_between(prior_start, window_start)

    last_sale = dict(
        db.query(SaleItem.product_id, func.max(Sale.created_at))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == company_id)
        .group_by(SaleItem.product_id)
        .all()
    )

    rows: List[Dict[str, Any]] = []
    for product in products:
        on_hand, sites = stock.get(product.id, (0, 0))
        units_sold, revenue = current.get(product.id, (0, 0.0))
        prior_units, _ = previous.get(product.id, (0, 0.0))

        # Divided by the whole window, not by days that had sales -- the same
        # trap the demand forecast fell into and had to be corrected for.
        daily_rate = units_sold / days if days else 0.0

        sold_at = last_sale.get(product.id)
        days_since = (now - sold_at).days if sold_at else None

        # None rather than a fabricated percentage when there is nothing to
        # compare against. "Infinite growth" from a base of zero is not growth.
        growth = (units_sold - prior_units) / prior_units if prior_units > 0 else None

        cost = float(product.unit_cost or 0)
        bucket = _classify(on_hand, daily_rate, days_since, growth)

        rows.append(
            {
                "id": str(product.id),
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "image_url": product.image_url,
                "status": product.status,
                "abc_class": product.abc_class,
                "created_at": product.created_at,
                "on_hand": on_hand,
                "sites": sites,
                "inventory_value": round(cost * on_hand, 2),
                "units_sold": units_sold,
                "revenue": round(revenue, 2),
                "daily_rate": round(daily_rate, 3),
                "days_cover": (
                    round(on_hand / daily_rate, 1) if daily_rate > 0 else None
                ),
                "days_since_sale": days_since,
                "growth": round(growth, 4) if growth is not None else None,
                "bucket": bucket,
            }
        )

    by_bucket: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BUCKETS}
    for row in rows:
        by_bucket[row["bucket"]].append(row)

    def top(items, key):
        return max(items, key=lambda r: r[key] or 0)["name"] if items else None

    recent_cutoff = now - timedelta(days=30)
    new_products = [r for r in rows if r["created_at"] >= recent_cutoff]
    discontinued = [r for r in rows if r["status"] != "active"]
    best_sellers = sorted(rows, key=lambda r: r["revenue"], reverse=True)[:20]
    best_sellers = [r for r in best_sellers if r["revenue"] > 0]
    growing = sorted(
        [r for r in rows if r["growth"] is not None and r["growth"] > 0],
        key=lambda r: r["growth"],
        reverse=True,
    )

    def workspace(key, label, items, value_key="inventory_value"):
        return {
            "key": key,
            "label": label,
            "count": len(items),
            "value": round(sum(r[value_key] for r in items), 2),
            "top_product": top(items, value_key),
            "sparkline": [r[value_key] for r in items[:12]],
        }

    #: Each workspace, with the order it should be read in. Sorting belongs here
    #: rather than in the browser: a workspace opened on the wrong row first is
    #: a list, and the point of a workspace is that the top row is the one that
    #: matters most.
    members = {
        "best_sellers": (best_sellers, lambda r: -r["revenue"]),
        "growing": (growing, lambda r: -(r["growth"] or 0)),
        "dead": (by_bucket["dead"], lambda r: -r["inventory_value"]),
        "at_risk": (
            by_bucket["critical"] + by_bucket["at_risk"],
            # Emptiest shelf first. Out of stock sorts above nearly out, which
            # is why the None case is forced to the top rather than the bottom.
            lambda r: r["days_cover"] if r["days_cover"] is not None else -1,
        ),
        "overstocked": (by_bucket["overstocked"], lambda r: -r["inventory_value"]),
        "new": (new_products, lambda r: -r["revenue"]),
        "discontinued": (discontinued, lambda r: -r["inventory_value"]),
    }

    return {
        "range_days": days,
        "definitions": {
            "dead_days": DEAD_DAYS,
            "overstock_cover_days": OVERSTOCK_COVER_DAYS,
            "at_risk_cover_days": AT_RISK_COVER_DAYS,
            "growth_threshold": GROWTH_THRESHOLD,
            "note": (
                "Each product is counted once, in the most urgent bucket that "
                "applies. A product both out of stock and growing is reported "
                "as critical, because the growth is why the stockout matters."
            ),
        },
        "kpis": {
            "total": len(rows),
            "active": sum(1 for r in rows if r["status"] == "active"),
            "best_sellers": len(best_sellers),
            "best_seller_revenue": round(sum(r["revenue"] for r in best_sellers), 2),
            "dead": len(by_bucket["dead"]),
            "dead_value": round(
                sum(r["inventory_value"] for r in by_bucket["dead"]), 2
            ),
            "at_risk": len(by_bucket["at_risk"]) + len(by_bucket["critical"]),
            "critical": len(by_bucket["critical"]),
            "overstocked": len(by_bucket["overstocked"]),
            "overstock_value": round(
                sum(r["inventory_value"] for r in by_bucket["overstocked"]), 2
            ),
            "growing": len(by_bucket["growing"]),
            "inventory_value": round(sum(r["inventory_value"] for r in rows), 2),
        },
        "distribution": [
            {
                "key": bucket,
                "count": len(by_bucket[bucket]),
                "value": round(sum(r["inventory_value"] for r in by_bucket[bucket]), 2),
            }
            for bucket in BUCKETS
        ],
        "workspaces": [
            workspace("best_sellers", "Best sellers", best_sellers, "revenue"),
            workspace("growing", "Fastest growing", growing, "revenue"),
            workspace("dead", "Dead inventory", by_bucket["dead"]),
            workspace(
                "at_risk", "Stockout risk", by_bucket["critical"] + by_bucket["at_risk"]
            ),
            workspace("overstocked", "Overstocked", by_bucket["overstocked"]),
            workspace("new", "New products", new_products),
            workspace("discontinued", "Discontinued", discontinued),
        ],
        # The catalogue, already classified, so the hub can filter without a
        # second request.
        #
        # Capped, because a hub is not a data export -- but the cap is applied
        # AFTER the workspace filter, never before. Sorting the whole catalogue
        # by revenue and taking the top 200 would silently drop every dead
        # product, since a dead product's defining feature is that it earned
        # nothing. The workspace that exists to find them would find none.
        "workspace": workspace_key,
        "products": (
            sorted(members[workspace_key][0], key=members[workspace_key][1])[:500]
            if workspace_key in members
            else sorted(rows, key=lambda r: r["revenue"], reverse=True)[:200]
        ),
    }
