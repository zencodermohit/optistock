"""What the assistant is allowed to ask the database.

Tool calling, not text-to-SQL. The model never writes a query; it picks from a
fixed set of read-only functions and supplies their arguments. That difference
is the whole security model:

*   **No arbitrary reads.** A generated `SELECT` is only as safe as whatever
    parses it, and every published defence against malicious SQL from a model is
    a filter someone eventually gets past. Here there is nothing to filter --
    the query is written by hand, at review time.
*   **The tenant is not an argument.** `company_id` comes from the verified JWT
    and is bound by the caller. It is deliberately absent from every schema
    below, so the model cannot supply it, cannot be argued into changing it, and
    cannot leak another company's data no matter what the user types.
*   **Nothing writes.** No tool adjusts stock, dismisses an alert or creates a
    record. An assistant that can only read cannot be talked into doing damage,
    and the actions all remain where a human clicks them.

Every tool returns its rows *and* the citations for them, so an answer can point
at the records it came from rather than asking to be believed.
"""

from typing import Any, Callable, Dict, List
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.alerts.models import STATUS_OPEN, Alert
from app.modules.analytics.accuracy import accuracy_summary
from app.modules.analytics.projections import recent_metrics
from app.modules.events.models import EventOutbox
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse

# How many rows any single tool may return. A model handed four hundred rows
# summarises them badly and burns the context it needs for the actual question;
# a capped list with a stated total is more useful than a truncated one that
# doesn't say it was truncated.
MAX_ROWS = 25


def _cite(kind: str, label: str, reference: str | None = None) -> Dict[str, str]:
    """One pointer back to a real record, for the UI to render under the answer."""
    return {"type": kind, "label": label, "ref": reference or label}


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------
def search_products(
    db: Session, company_id: UUID, query: str = "", abc_class: str = ""
):
    q = db.query(Product).filter(Product.company_id == company_id)
    if query:
        pattern = f"%{query}%"
        q = q.filter(Product.sku.ilike(pattern) | Product.name.ilike(pattern))
    if abc_class:
        q = q.filter(Product.abc_class == abc_class.upper())

    total = q.count()
    rows = q.order_by(Product.sku).limit(MAX_ROWS).all()

    return {
        "total_matching": total,
        "showing": len(rows),
        "products": [
            {
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "abc_class": p.abc_class,
                "unit_cost": float(p.unit_cost or 0),
                "selling_price": float(p.selling_price or 0),
                "status": p.status,
            }
            for p in rows
        ],
        "_citations": [_cite("product", p.sku, p.name) for p in rows[:8]],
    }


def check_stock(db: Session, company_id: UUID, sku: str = "", low_only: bool = False):
    q = (
        db.query(
            Product.sku,
            Product.name.label("product_name"),
            Warehouse.name.label("warehouse_name"),
            Inventory.quantity,
            Inventory.reorder_point,
        )
        .join(Product, Inventory.product_id == Product.id)
        .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
        .filter(Product.company_id == company_id, Warehouse.company_id == company_id)
    )
    if sku:
        q = q.filter(Product.sku.ilike(f"%{sku}%"))
    if low_only:
        q = q.filter(
            Inventory.reorder_point > 0,
            Inventory.quantity <= Inventory.reorder_point,
        )

    total = q.count()
    rows = q.order_by(Inventory.quantity.asc()).limit(MAX_ROWS).all()

    return {
        "total_matching": total,
        "showing": len(rows),
        "stock_lines": [
            {
                "sku": r.sku,
                "product": r.product_name,
                "warehouse": r.warehouse_name,
                "on_hand": r.quantity,
                "reorder_point": r.reorder_point,
                "is_low": bool(r.reorder_point and r.quantity <= r.reorder_point),
            }
            for r in rows
        ],
        "_citations": [
            _cite("stock", f"{r.sku} @ {r.warehouse_name}", r.product_name)
            for r in rows[:8]
        ],
    }


def list_alerts(db: Session, company_id: UUID, severity: str = ""):
    q = db.query(Alert).filter(
        Alert.company_id == company_id, Alert.status == STATUS_OPEN
    )
    if severity:
        q = q.filter(Alert.severity == severity.lower())

    total = q.count()
    rows = q.order_by(Alert.created_at.desc()).limit(MAX_ROWS).all()

    return {
        "total_open": total,
        "showing": len(rows),
        "alerts": [
            {
                "severity": a.severity,
                "type": a.alert_type,
                "title": a.title,
                # The evidence, so the model can explain WHY an alert fired
                # rather than restating its title back at the user.
                "evidence": a.detail,
                "raised_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "_citations": [_cite("alert", a.title, a.severity) for a in rows[:8]],
    }


def trading_summary(db: Session, company_id: UUID, days: int = 30):
    days = max(7, min(int(days or 30), 90))
    series = recent_metrics(db, company_id, days=days)

    revenue = sum(d["revenue"] for d in series)
    busiest = max(series, key=lambda d: d["revenue"]) if series else None

    return {
        "window_days": days,
        "revenue": round(revenue, 2),
        "orders": sum(d["orders"] for d in series),
        "units_sold": sum(d["units_sold"] for d in series),
        "stock_movements": sum(d["stock_movements"] for d in series),
        "busiest_day": (
            {"date": busiest["date"], "revenue": round(busiest["revenue"], 2)}
            if busiest
            else None
        ),
        # Stated rather than assumed: these figures come from a read model a
        # background worker maintains, and the model should say so if asked how
        # current they are.
        "source": "daily_metrics projection, maintained by the event consumers",
        "_citations": [_cite("report", f"Trading, last {days} days")],
    }


def forecast_accuracy(db: Session, company_id: UUID):
    summary = accuracy_summary(db, company_id)
    return {
        **summary,
        "metric": (
            "weighted_ape is total units missed divided by total units sold, not "
            "the average of per-product percentages"
        ),
        "_citations": [_cite("report", "Forecast accuracy")],
    }


def recent_events(db: Session, company_id: UUID, event_type: str = "", limit: int = 15):
    q = db.query(EventOutbox).filter(EventOutbox.company_id == company_id)
    if event_type:
        q = q.filter(EventOutbox.event_type == event_type)

    rows = (
        q.order_by(EventOutbox.sequence.desc())
        .limit(max(1, min(int(limit or 15), MAX_ROWS)))
        .all()
    )

    return {
        "showing": len(rows),
        "events": [
            {
                "sequence": e.sequence,
                "type": e.event_type,
                "at": e.occurred_at.isoformat(),
                "payload": e.payload,
            }
            for e in rows
        ],
        "_citations": [
            _cite("event", f"#{e.sequence} {e.event_type}") for e in rows[:8]
        ],
    }


def warehouse_overview(db: Session, company_id: UUID):
    rows = (
        db.query(
            Warehouse.name,
            func.count(Inventory.id).label("lines"),
            func.coalesce(func.sum(Inventory.quantity), 0).label("units"),
        )
        .outerjoin(Inventory, Inventory.warehouse_id == Warehouse.id)
        .filter(Warehouse.company_id == company_id)
        .group_by(Warehouse.id, Warehouse.name)
        .order_by(Warehouse.name)
        .all()
    )
    return {
        "warehouses": [
            {"name": r.name, "stock_lines": r.lines, "units_held": int(r.units)}
            for r in rows
        ],
        "_citations": [_cite("warehouse", r.name) for r in rows],
    }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
EXECUTORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "search_products": search_products,
    "check_stock": check_stock,
    "list_alerts": list_alerts,
    "trading_summary": trading_summary,
    "forecast_accuracy": forecast_accuracy,
    "recent_events": recent_events,
    "warehouse_overview": warehouse_overview,
}

# Descriptions say WHEN to call each tool, not just what it does. A description
# that only states capability leaves the model guessing at applicability, and
# guessing shows up as the wrong tool or no tool at all.
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_products",
        "description": (
            "Look up products in the catalogue by name, SKU fragment, or ABC class. "
            "Call this when the user names a product or asks what the company "
            "sells, how something is priced, or which products are A/B/C class. "
            "Returns cost, price and classification. Does NOT return stock levels "
            "-- use check_stock for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to match against product name or SKU.",
                },
                "abc_class": {
                    "type": "string",
                    "enum": ["A", "B", "C"],
                    "description": "Restrict to one revenue class.",
                },
            },
        },
    },
    {
        "name": "check_stock",
        "description": (
            "Current stock on hand per product per warehouse, with reorder points. "
            "Call this for anything about quantities, what is running low, what is "
            "out of stock, or how much of something is held where. Set low_only to "
            "true when the user asks what needs reordering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": "Restrict to SKUs matching this text.",
                },
                "low_only": {
                    "type": "boolean",
                    "description": "Only lines at or below their reorder point.",
                },
            },
        },
    },
    {
        "name": "list_alerts",
        "description": (
            "Open alerts raised by the background consumers, each with the evidence "
            "that fired it. Call this when the user asks what needs attention, what "
            "is wrong, or about warnings and critical issues."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "Restrict to one severity.",
                },
            },
        },
    },
    {
        "name": "trading_summary",
        "description": (
            "Revenue, orders, units sold and stock movements over a recent window. "
            "Call this for any question about sales performance, how business is "
            "going, or totals over a period. Window is 7-90 days; defaults to 30."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Length of the window in days (7-90).",
                },
            },
        },
    },
    {
        "name": "forecast_accuracy",
        "description": (
            "How well the demand forecast has actually performed against real "
            "sales: weighted error, average miss in units, and how many predictions "
            "landed within 20%. Call this whenever the user asks whether the "
            "forecast or the AI can be trusted, or how accurate predictions are."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "recent_events",
        "description": (
            "The most recent domain events from the event log -- stock movements, "
            "sales, scans, threshold crossings. Call this when the user asks what "
            "has been happening, what changed recently, or about activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": (
                        "Exact event type, e.g. stock.moved, sale.completed, "
                        "stock.depleted, scan.recorded."
                    ),
                },
                "limit": {"type": "integer", "description": "How many events (1-25)."},
            },
        },
    },
    {
        "name": "warehouse_overview",
        "description": (
            "Every warehouse with how many stock lines and units it holds. Call "
            "this when the user asks about locations, sites, or where stock sits."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def run_tool(db: Session, company_id: UUID, name: str, arguments: Dict[str, Any]):
    """Execute one tool call. Returns (payload_for_the_model, citations).

    `company_id` is passed positionally by this function and is never read from
    `arguments` -- the model's arguments are merged in around it, so a model
    that invented a company_id field would have it silently ignored rather than
    honoured.
    """
    executor = EXECUTORS.get(name)
    if executor is None:
        return {"error": f"No such tool: {name}"}, []

    safe_arguments = {
        key: value
        for key, value in (arguments or {}).items()
        if key not in {"company_id", "db"}
    }

    try:
        result = executor(db, company_id, **safe_arguments)
    except TypeError as e:
        # A hallucinated argument name should read as a correctable mistake, not
        # a crashed request -- the model can retry with the right shape.
        return {"error": f"Invalid arguments for {name}: {e}"}, []

    citations = result.pop("_citations", [])
    return result, citations
