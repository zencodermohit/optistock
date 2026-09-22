"""Raising a purchase order from a recommendation.

The card on the procurement screen says "order 240 of this". The button next
to it is supposed to do that. For a long time it could not, and not because
nobody had written the click handler: the row published the supplier and the
warehouse as NAMES, while creating an order needs their ids. Both were
computed server side and discarded a line before the response was built, so
there was nothing valid for a handler to send even if one had existed.

These hold the loop down end to end -- the row carries what an order needs,
and raising one takes the card away.
"""

from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.purchase_orders.procurement import procurement
from app.modules.recommendations.models import Recommendation
from app.modules.suppliers.models import Supplier


def _setup(db_session, company, warehouse, product, quantity=12):
    """A product with a past supplier and a live recommendation."""
    supplier = Supplier(
        company_id=company.id, name="Acme Supply", contact_email="a@b.com"
    )
    db_session.add(supplier)
    db_session.flush()

    # The supplier is inferred from who last supplied the product, so there has
    # to be a delivered order for one to exist at all.
    order = PurchaseOrder(
        company_id=company.id,
        supplier_id=supplier.id,
        destination_warehouse_id=warehouse.id,
        status="delivered",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        POItem(po_id=order.id, product_id=product.id, quantity=5, unit_price=100.0)
    )

    db_session.add(
        Recommendation(
            product_id=product.id,
            warehouse_id=warehouse.id,
            suggested_action="reorder",
            suggested_quantity=quantity,
            confidence_score=70,
            evidence={"forecast_quantity": quantity, "avg_daily_sales": 1.0},
            business_reasoning="Forecast demand exceeds stock on hand.",
            source="forecast",
        )
    )
    db_session.commit()
    return supplier


def test_the_row_carries_what_an_order_actually_needs(
    db_session, company, make_warehouse, make_product
):
    """Ids, not names.

    This is the assertion that would have caught the original bug. The card
    displayed a supplier and a warehouse and looked complete, while carrying
    nothing an API call could use.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="RAISE-1", unit_cost=100)
    supplier = _setup(db_session, company, warehouse, product)

    data = procurement(db_session, company.id)
    row = next(r for r in data["recommendations"] if r["sku"] == "RAISE-1")

    assert row["supplier_id"] == str(supplier.id)
    assert row["warehouse_id"] == str(warehouse.id)
    assert row["unit_cost"] > 0


def test_raising_the_order_takes_the_card_away(
    authenticated_client, db_session, company, make_warehouse, make_product
):
    """The whole loop, as the button drives it.

    The list hides any product with an order already open for that warehouse,
    so a successful raise must remove the card. If it did not, the obvious
    thing to do next is press the button again.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="RAISE-2", unit_cost=100)
    supplier = _setup(db_session, company, warehouse, product, quantity=12)

    before = procurement(db_session, company.id)
    assert any(r["sku"] == "RAISE-2" for r in before["recommendations"])

    response = authenticated_client.post(
        "/api/v1/purchase_orders/",
        json={
            "supplier_id": str(supplier.id),
            "destination_warehouse_id": str(warehouse.id),
            "items": [
                {
                    "product_id": str(product.id),
                    "quantity": 12,
                    "unit_price": 100.0,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text

    db_session.expire_all()
    after = procurement(db_session, company.id)
    assert not any(r["sku"] == "RAISE-2" for r in after["recommendations"])


def test_a_product_nobody_has_ever_supplied_has_no_supplier_to_order_from(
    db_session, company, make_warehouse, make_product
):
    """Null, not a guess.

    A purchase order is addressed to somebody. With no past order there is
    nothing to infer a supplier from, and the screen disables the button rather
    than inventing one -- so this has to be reported honestly rather than
    falling back to whichever supplier happens to be first.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="ORPHAN-1", unit_cost=50)
    db_session.add(
        Recommendation(
            product_id=product.id,
            warehouse_id=warehouse.id,
            suggested_action="reorder",
            suggested_quantity=4,
            confidence_score=40,
            evidence={"forecast_quantity": 4, "avg_daily_sales": 0.5},
            business_reasoning="Forecast demand exceeds stock on hand.",
            source="forecast",
        )
    )
    db_session.commit()

    data = procurement(db_session, company.id)
    row = next(r for r in data["recommendations"] if r["sku"] == "ORPHAN-1")

    assert row["supplier_id"] is None
    assert row["supplier"] is None
    # The warehouse is still known: it is the recommendation's own column.
    assert row["warehouse_id"] == str(warehouse.id)
