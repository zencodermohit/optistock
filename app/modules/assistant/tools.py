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
*   **Nothing here changes the business.** No tool adjusts stock, dismisses an
    alert or places an order. One tool writes at all -- create_purchase_order --
    and what it writes is a proposal in a table nothing downstream watches. It
    becomes a purchase order when a person approves it on the Approvals screen
    and not before, so the worst a confused model can do is put a bad
    suggestion in a human's queue.

Every tool returns its rows *and* the citations for them, so an answer can point
at the records it came from rather than asking to be believed.
"""

from copy import deepcopy
from typing import Any, Callable, Dict, List
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.alerts.models import STATUS_OPEN, Alert
from app.modules.analytics.accuracy import accuracy_summary
from app.modules.analytics.projections import recent_metrics
from app.modules.analytics.stockout import stockout_risks, summarise
from app.modules.assistant import cache
from app.modules.events.models import EventOutbox
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse

# How many rows any single tool may return. A model handed four hundred rows
# summarises them badly and burns the context it needs for the actual question;
# a capped list with a stated total is more useful than a truncated one that
# doesn't say it was truncated.
MAX_ROWS = 25


def _cite(kind: str, ref: str, label: str | None = None) -> Dict[str, str]:
    """One pointer back to a real record, for the UI to render under the answer.

    `ref` identifies the record -- a SKU, an alert title, an event sequence --
    and is what de-duplication keys on. `label` is the human description shown
    alongside it.

    These two were reversed, and every call site already passed them in this
    order, so the identifier ended up in `label` and the description in `ref`.
    Cosmetic for products, but alerts cite their severity as the description:
    with that in `ref`, every open warning de-duplicated to a single citation
    and an answer drawing on six alerts appeared to rest on one.
    """
    return {"type": kind, "ref": ref, "label": label or ref}


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


def stockout_risk(db: Session, company_id: UUID, days: int = 0, limit: int = 10):
    """What runs out first, with the numbers behind each prediction.

    The explanation is computed server-side and handed to the model rather than
    left for it to assemble. A model given four numbers will write a fifth, and
    a stockout date it derived itself is a stockout date nobody can check.
    """
    risks = stockout_risks(db, company_id, limit=min(max(int(limit or 10), 1), MAX_ROWS))

    if days:
        window = max(int(days), 1)
        risks = [
            r
            for r in risks
            if r.days_remaining is not None and r.days_remaining <= window
        ]

    return {
        "summary": summarise(risks),
        # Stated with the answers rather than buried in a config file. An
        # "optimal" order quantity is only as meaningful as the costs it was
        # optimised against, and the model should be able to say so when asked
        # where the number came from.
        "assumptions": {
            "lead_time_days": settings.SUPPLIER_LEAD_TIME_DAYS,
            "order_cost": settings.ORDER_COST,
            "holding_cost_rate": settings.HOLDING_COST_RATE,
            "note": (
                "Order quantity is EOQ; the reorder point covers the lead time "
                "plus a buffer for days busier than average."
            ),
        },
        "at_risk": [
            {
                "sku": r.sku,
                "product_name": r.product_name,
                "warehouse": r.warehouse_name,
                "on_hand": r.on_hand,
                "reorder_point": r.reorder_point,
                "daily_usage": r.daily_usage,
                "days_remaining": r.days_remaining,
                "runs_out_on": r.stockout_date,
                "severity": r.severity,
                "confidence": r.confidence,
                "order_quantity": r.order_quantity,
                "suggested_reorder_point": r.suggested_reorder_point,
                "why": r.explanation,
            }
            for r in risks
        ],
        "_citations": [
            _cite("stock", f"{r.sku} @ {r.warehouse_name}", r.product_name)
            for r in risks[:8]
        ],
    }


# ---------------------------------------------------------------------------
# The one tool that is not a read
#
# And it still is not a write. It records a suggestion and returns its id. The
# purchase order does not exist until a person opens the approvals screen and
# says so, which is why the return value leads with requires_approval -- the
# model is being told, in the same breath as its success, that it has not
# actually done anything.
# ---------------------------------------------------------------------------
def create_purchase_order(
    db: Session,
    company_id: UUID,
    sku: str = "",
    quantity: int = 0,
    reason: str = "",
    _context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from app.modules.assistant.actions import ActionService

    context = _context or {}
    action, error = ActionService(db).propose_purchase_order(
        company_id=company_id,
        sku=sku,
        quantity=quantity,
        rationale=reason,
        source_question=context.get("question"),
        model=context.get("model"),
        requested_by_user_id=context.get("user_id"),
    )

    if error is not None:
        # Correctable, like every other tool failure -- the model can fix the
        # SKU and try again rather than apologising for a crash.
        return {"error": error, "requires_approval": True, "_citations": []}

    # Committed here rather than left to a router. This endpoint streams, so
    # there is no tidy request boundary to commit at, and a proposal that
    # vanished because the model errored two seconds later would be a proposal
    # the user watched being made and then could not find.
    db.commit()

    payload = action.proposed_payload
    return {
        "status": "proposed",
        "requires_approval": True,
        "action_id": str(action.id),
        "message": (
            "Nothing has been ordered. This is a proposal awaiting human "
            "approval on the Approvals screen."
        ),
        "sku": payload["sku"],
        "product_name": payload["product_name"],
        "quantity": payload["quantity"],
        "estimated_total": payload["estimated_total"],
        "destination": payload["warehouse_name"],
        "supplier": payload["supplier_name"],
        "expires_in_hours": 24,
        "_citations": [
            _cite("proposal", f"Proposed order: {payload['quantity']} x {payload['sku']}")
        ],
    }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
#: Tools that need to know who is asking. Their context is injected by
#: `run_tool` from the request, never from the model's arguments.
NEEDS_CONTEXT = frozenset({"create_purchase_order"})

EXECUTORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "create_purchase_order": create_purchase_order,
    "search_products": search_products,
    "check_stock": check_stock,
    "list_alerts": list_alerts,
    "trading_summary": trading_summary,
    "forecast_accuracy": forecast_accuracy,
    "recent_events": recent_events,
    "warehouse_overview": warehouse_overview,
    "stockout_risk": stockout_risk,
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
    {
        "name": "stockout_risk",
        "description": (
            "Predicts WHEN each product runs out, ranked soonest first, with the "
            "numbers behind each prediction: units on hand, reorder point, daily "
            "usage rate, days remaining and the projected date. Call this for "
            "'what will run out', 'what should I worry about', 'how long will X "
            "last', or any question about urgency or timing. Prefer this over "
            "check_stock when the user cares about WHEN rather than HOW MUCH -- "
            "check_stock compares against a static threshold, this one uses "
            "actual sales velocity. Each row carries a 'why' sentence; quote it "
            "rather than recomputing the arithmetic yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": (
                        "Only return lines running out within this many days. "
                        "Omit for everything, ranked by urgency."
                    ),
                },
                "limit": {"type": "integer", "description": "How many rows (1-25)."},
            },
        },
    },
    {
        "name": "create_purchase_order",
        "description": (
            "PROPOSE a purchase order for a human to approve. This does NOT place "
            "an order and does NOT change stock -- it creates a suggestion that "
            "appears on the Approvals screen, where a person accepts, amends or "
            "rejects it. Call this when the user asks you to reorder or restock "
            "something, or agrees to a reorder you recommended. Always tell the "
            "user afterwards that it is awaiting their approval and that nothing "
            "has been ordered yet. Check the current level with check_stock first "
            "so the quantity is justified, and say why in the reason."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": "Exact SKU of the product to reorder.",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Units to order. Must be positive.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why this quantity, in one sentence, citing the numbers "
                        "you saw. The approver reads this."
                    ),
                },
            },
            "required": ["sku", "quantity"],
        },
    },
]


def run_tool(
    db: Session,
    company_id: UUID,
    name: str,
    arguments: Dict[str, Any],
    context: Dict[str, Any] | None = None,
):
    """Execute one tool call. Returns (payload_for_the_model, citations).

    `company_id` is passed positionally by this function and is never read from
    `arguments` -- the model's arguments are merged in around it, so a model
    that invented a company_id field would have it silently ignored rather than
    honoured.

    `context` carries who is asking, for the tools that must record it. It comes
    from the request and is stripped from the model's arguments for the same
    reason company_id is: a field the model can set is a field an injection can
    set, and "who requested this order" is not a question the model gets a vote
    on.
    """
    executor = EXECUTORS.get(name)
    if executor is None:
        return {"error": f"No such tool: {name}"}, []

    safe_arguments = {
        key: value
        for key, value in (arguments or {}).items()
        if key not in {"company_id", "db", "_context"}
    }

    # Cached on the normalised arguments, after the tenant fields are stripped,
    # so a model that supplied a company_id cannot use it to vary the key. The
    # key carries the real company_id regardless -- see cache.py.
    cached = cache.get(company_id, name, safe_arguments)
    if cached is not None:
        payload, citations = cached
        # Copied on the way out. A caller that mutates a result -- the redactor
        # does exactly that -- must not be editing the cached entry, or the next
        # reader gets someone's pseudonyms.
        return deepcopy(payload), deepcopy(citations)

    if name in NEEDS_CONTEXT:
        safe_arguments["_context"] = context or {}

    try:
        result = executor(db, company_id, **safe_arguments)
    except TypeError as e:
        # A hallucinated argument name should read as a correctable mistake, not
        # a crashed request -- the model can retry with the right shape.
        return {"error": f"Invalid arguments for {name}: {e}"}, []

    citations = result.pop("_citations", [])
    cache.put(company_id, name, safe_arguments, (result, citations))
    return deepcopy(result), deepcopy(citations)
