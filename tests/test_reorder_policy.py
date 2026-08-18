"""EOQ and safety stock, finally connected to something.

Both formulas were written, unit-tested and never called. Nothing was wrong
with them — they needed three numbers the schema does not hold, and inventing
those quietly would have been worse than leaving them unused. These tests cover
the wiring: real demand in, a policy out, and the assumptions visible.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.stockout import stockout_risks
from app.modules.assistant.tools import run_tool
from app.modules.sales.models import Sale, SaleItem


@pytest.fixture
def sell(db_session, company, make_customer):
    customer = make_customer(company)

    def _sell(product, warehouse, quantity, days_ago=1):
        sale = Sale(
            company_id=company.id,
            customer_id=customer.id,
            source_warehouse_id=warehouse.id,
            status="completed",
            total_amount=quantity * 10,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=10,
            )
        )
        db_session.flush()

    return _sell


def test_a_selling_product_gets_an_order_quantity_and_a_reorder_point(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    product = make_product(company, sku="POLICY-1")
    product.unit_cost = 25
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=300)
    for day in range(1, 21):
        sell(product, warehouse, 10, days_ago=day)
    db_session.commit()

    risk = next(
        r for r in stockout_risks(db_session, company.id) if r.sku == "POLICY-1"
    )

    assert risk.order_quantity and risk.order_quantity > 0
    assert risk.suggested_reorder_point and risk.suggested_reorder_point > 0
    assert risk.safety_stock is not None
    # The reorder point must at least cover the lead time at the usual rate,
    # otherwise it would order too late by construction.
    assert risk.suggested_reorder_point >= risk.daily_usage * 7


def test_safety_stock_is_sized_on_the_busiest_day_not_the_average(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The whole reason a peak is queried at daily grain.

    Two products with identical total demand but different shapes need
    different buffers: the spiky one can empty a shelf in a day that the steady
    one never would.
    """
    warehouse = make_warehouse(company)

    steady = make_product(company, sku="STEADY-1")
    steady.unit_cost = 25
    make_stock(steady, warehouse, quantity=500)
    for day in range(1, 21):
        sell(steady, warehouse, 10, days_ago=day)

    spiky = make_product(company, sku="SPIKY-1")
    spiky.unit_cost = 25
    make_stock(spiky, warehouse, quantity=500)
    sell(spiky, warehouse, 200, days_ago=5)
    db_session.commit()

    rows = {r.sku: r for r in stockout_risks(db_session, company.id)}

    assert rows["SPIKY-1"].peak_daily_usage > rows["STEADY-1"].peak_daily_usage
    assert rows["SPIKY-1"].safety_stock > rows["STEADY-1"].safety_stock


def test_a_product_with_no_demand_gets_no_policy(
    db_session, company, make_product, make_warehouse, make_stock
):
    """No recommendation is the right answer, not a recommendation of zero."""
    product = make_product(company, sku="NODEMAND-1")
    product.unit_cost = 25
    make_stock(product, make_warehouse(company), quantity=40)
    db_session.commit()

    risk = next(
        r for r in stockout_risks(db_session, company.id) if r.sku == "NODEMAND-1"
    )

    assert risk.order_quantity is None
    assert risk.suggested_reorder_point is None


def test_a_product_with_no_cost_gets_no_policy(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """EOQ divides by holding cost, which is derived from unit cost. The helper
    refuses the input rather than returning a nonsense number, and that refusal
    is honoured rather than papered over."""
    product = make_product(company, sku="FREE-POL")
    product.unit_cost = 0
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=100)
    for day in range(1, 11):
        sell(product, warehouse, 5, days_ago=day)
    db_session.commit()

    risk = next(
        r for r in stockout_risks(db_session, company.id) if r.sku == "FREE-POL"
    )

    assert risk.order_quantity is None
    # But the risk itself is still computed — it sells, so it can still run out.
    assert risk.days_remaining is not None


def test_a_cheaper_product_gets_a_larger_economic_order(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """EOQ's actual claim: when holding is cheap relative to ordering, order
    more at once. If this inverted, the formula would be wired up backwards."""
    warehouse = make_warehouse(company)

    cheap = make_product(company, sku="CHEAP-1")
    cheap.unit_cost = 5
    make_stock(cheap, warehouse, quantity=1000)

    dear = make_product(company, sku="DEAR-1")
    dear.unit_cost = 500
    make_stock(dear, warehouse, quantity=1000)

    for day in range(1, 21):
        sell(cheap, warehouse, 10, days_ago=day)
        sell(dear, warehouse, 10, days_ago=day)
    db_session.commit()

    rows = {r.sku: r for r in stockout_risks(db_session, company.id)}

    assert rows["CHEAP-1"].order_quantity > rows["DEAR-1"].order_quantity


def test_the_assistant_can_see_the_policy(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """So "what should I order?" is answered with a number the system computed
    rather than one the model invented."""
    product = make_product(company, sku="TOOLPOL-1")
    product.unit_cost = 25
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=60)
    for day in range(1, 11):
        sell(product, warehouse, 20, days_ago=day)
    db_session.commit()

    result, _ = run_tool(db_session, company.id, "stockout_risk", {})
    row = next(r for r in result["at_risk"] if r["sku"] == "TOOLPOL-1")

    assert row["order_quantity"] > 0
    assert row["suggested_reorder_point"] > 0
    # And the assumptions behind them travel with the answer.
    assert result["assumptions"]["lead_time_days"] == 7
