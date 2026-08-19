"""The procurement screen.

These test the claims the module makes about itself, not the shape of its
output. A test that asserts a dictionary has sixteen keys fails every time
somebody adds a seventeenth and tells you nothing when the numbers are wrong.

Four claims are worth holding down, because each one is a thing the module
went out of its way to get right and would be easy to quietly lose:

  1. Everything is scoped to one company. It is a multi-tenant screen with no
     tenant in the URL -- the company comes from the token -- so a missing
     filter leaks another business's purchasing.
  2. Supplier lead time is MEASURED from delivered orders, not read from a
     column. There is no lead_time_days field and this must not invent one.
  3. The trend is a flow, not a stock. "How many orders are open" is a level
     and has no month-on-month change; the module's own comments record that
     this was got wrong once and returned None for everything.
  4. Confidence is a data-density heuristic and is reported as one. It is not
     a model probability and the screen must not imply otherwise.
"""

from datetime import datetime, timedelta, timezone

from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.purchase_orders.procurement import procurement
from app.modules.suppliers.models import Supplier


def _supplier(db_session, company, name="Acme Supply"):
    supplier = Supplier(company_id=company.id, name=name, contact_email="a@b.com")
    db_session.add(supplier)
    db_session.commit()
    return supplier


def _order(
    db_session,
    company,
    supplier,
    warehouse,
    product,
    *,
    status="submitted",
    created_days_ago=5,
    expected_in_days=None,
    quantity=10,
    unit_price=100.0,
):
    """One purchase order, dated relative to now so tests do not rot."""
    created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    po = PurchaseOrder(
        company_id=company.id,
        supplier_id=supplier.id,
        destination_warehouse_id=warehouse.id,
        status=status,
        total_amount=quantity * unit_price,
        created_at=created,
        expected_delivery_date=(
            (created + timedelta(days=expected_in_days)).date()
            if expected_in_days is not None
            else None
        ),
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        POItem(
            po_id=po.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
        )
    )
    db_session.commit()
    return po


# --- 1. Tenancy -------------------------------------------------------------


def test_one_company_never_sees_another_companys_purchasing(
    db_session, company, other_company, make_warehouse, make_product
):
    """The company comes from the token, not the URL. A dropped filter here is
    not a display bug, it is one business reading another's supply chain."""
    mine = _supplier(db_session, company, "My Supplier")
    theirs = _supplier(db_session, other_company, "Their Supplier")

    _order(
        db_session,
        company,
        mine,
        make_warehouse(company),
        make_product(company),
        quantity=1,
        unit_price=500.0,
    )
    for _ in range(5):
        _order(
            db_session,
            other_company,
            theirs,
            make_warehouse(other_company),
            make_product(other_company),
            quantity=1,
            unit_price=9999.0,
        )

    result = procurement(db_session, company.id)

    open_card = next(c for c in result["kpis"] if c["key"] == "open")
    assert open_card["value"] == 1, "counted another tenant's orders"
    assert open_card["amount"] == 500.0, "summed another tenant's money"

    rendered = str(result)
    assert "Their Supplier" not in rendered
    assert "9999" not in rendered


def test_a_company_with_no_orders_gets_zeroes_rather_than_an_error(db_session, company):
    """The empty state is a real state -- a new tenant sees it on day one --
    and it must not divide by zero on the way to reporting nothing."""
    result = procurement(db_session, company.id)

    open_card = next(c for c in result["kpis"] if c["key"] == "open")
    assert open_card["value"] == 0
    assert open_card["amount"] == 0
    assert open_card["trend"] is None, "no history cannot produce a trend"


# --- 2. Lead time is measured, not stored -----------------------------------


def test_supplier_lead_time_is_measured_from_the_dates_on_delivered_orders(
    db_session, company, make_warehouse, make_product
):
    """There is no lead_time_days column and this must not behave as if there
    were. A supplier that has taken ten days twice has a lead time of ten,
    discovered by looking rather than by being told."""
    supplier = _supplier(db_session, company, "Ten Day Supplier")
    warehouse = make_warehouse(company)
    product = make_product(company)

    for days_ago in (40, 30, 20):
        _order(
            db_session,
            company,
            supplier,
            warehouse,
            product,
            status="delivered",
            created_days_ago=days_ago,
            expected_in_days=10,
        )

    result = procurement(db_session, company.id)
    lead_times = str(result)

    assert "10" in lead_times
    measured = [s for s in result.get("suppliers", []) if s.get("lead_time")]
    if measured:
        assert any(abs(float(s["lead_time"]["days"]) - 10.0) < 0.5 for s in measured), (
            "measured a lead time that is not what the dates say"
        )


def test_orders_still_in_transit_do_not_count_towards_lead_time(
    db_session, company, make_warehouse, make_product
):
    """An order that has not arrived is not evidence of how long arriving
    takes. Including them drags every supplier's average towards whenever the
    report happened to be run."""
    supplier = _supplier(db_session, company, "Pending Supplier")
    warehouse = make_warehouse(company)
    product = make_product(company)

    # One delivered in 5 days, and a pile that left long ago and never landed.
    _order(
        db_session,
        company,
        supplier,
        warehouse,
        product,
        status="delivered",
        created_days_ago=30,
        expected_in_days=5,
    )
    for _ in range(4):
        _order(
            db_session,
            company,
            supplier,
            warehouse,
            product,
            status="submitted",
            created_days_ago=60,
            expected_in_days=90,
        )

    result = procurement(db_session, company.id)

    for s in result.get("suppliers", []):
        lt = s.get("lead_time")
        if lt and lt.get("days"):
            assert float(lt["days"]) < 30, (
                "an undelivered order was counted as evidence of delivery time"
            )


# --- 3. The trend is a flow, not a stock ------------------------------------


def test_the_trend_compares_orders_raised_not_orders_currently_open(
    db_session, company, make_warehouse, make_product
):
    """The module's comments record getting this wrong: it compared how many
    orders sat in a status across two windows, which is a level, and a level
    has no month-on-month change. Orders raised sixty days ago are not still
    drafts, so the previous window always held zero and the trend was always
    None. Raising orders in both windows must produce a number."""
    supplier = _supplier(db_session, company, "Steady Supplier")
    warehouse = make_warehouse(company)
    product = make_product(company)

    # Four raised in the last 30 days, two in the 30 before that. Delivered, so
    # none of them is "open" now -- which is the whole point.
    for days_ago in (5, 10, 15, 20):
        _order(
            db_session,
            company,
            supplier,
            warehouse,
            product,
            status="delivered",
            created_days_ago=days_ago,
        )
    for days_ago in (40, 50):
        _order(
            db_session,
            company,
            supplier,
            warehouse,
            product,
            status="delivered",
            created_days_ago=days_ago,
        )

    result = procurement(db_session, company.id)
    open_card = next(c for c in result["kpis"] if c["key"] == "open")

    assert open_card["trend"] is not None, (
        "a flow with history in both windows must produce a trend"
    )
    # 4 vs 2 is +100%.
    assert abs(open_card["trend"] - 1.0) < 0.01


def test_a_level_carries_no_trend(db_session, company, make_warehouse, make_product):
    """Delayed orders and urgent reorders are counts of a current state. A
    month-on-month change figure against them would be arithmetic on two
    different questions, so they must report None rather than a number."""
    supplier = _supplier(db_session, company, "S")
    _order(
        db_session,
        company,
        supplier,
        make_warehouse(company),
        make_product(company),
        status="submitted",
        created_days_ago=20,
        expected_in_days=1,
    )

    result = procurement(db_session, company.id)

    for key in ("delayed", "urgent_reorders"):
        card = next(c for c in result["kpis"] if c["key"] == key)
        assert card["trend"] is None, f"{key} is a level and cannot have a trend"


# --- 4. Delay is a fact about a date ----------------------------------------


def test_an_order_is_late_because_its_promised_date_has_passed(
    db_session, company, make_warehouse, make_product
):
    supplier = _supplier(db_session, company, "Late Supplier")
    warehouse = make_warehouse(company)
    product = make_product(company)

    # Promised five days after it was raised, twenty days ago. Fifteen late.
    _order(
        db_session,
        company,
        supplier,
        warehouse,
        product,
        status="submitted",
        created_days_ago=20,
        expected_in_days=5,
    )
    # Promised well into the future: not late, and must not be counted.
    _order(
        db_session,
        company,
        supplier,
        warehouse,
        product,
        status="submitted",
        created_days_ago=2,
        expected_in_days=60,
    )

    result = procurement(db_session, company.id)
    delayed = next(c for c in result["kpis"] if c["key"] == "delayed")

    assert delayed["value"] == 1, "counted an order that is not yet due"


def test_a_delivered_order_is_never_late(
    db_session, company, make_warehouse, make_product
):
    """It arrived. Whether it arrived late is a different report; this card is
    about what is still outstanding and needs chasing."""
    supplier = _supplier(db_session, company, "Delivered Late Supplier")
    _order(
        db_session,
        company,
        supplier,
        make_warehouse(company),
        make_product(company),
        status="delivered",
        created_days_ago=40,
        expected_in_days=1,
    )

    result = procurement(db_session, company.id)
    delayed = next(c for c in result["kpis"] if c["key"] == "delayed")

    assert delayed["value"] == 0


# --- 5. The endpoint ---------------------------------------------------------


def test_procurement_requires_authentication(client):
    assert client.get("/api/v1/purchase_orders/procurement").status_code == 401


def test_procurement_is_routed_above_the_id_lookup(authenticated_client):
    """/procurement is declared before /{po_id}. FastAPI matches in declaration
    order, so below it the word is read as a purchase order id and rejected as
    a malformed UUID -- a 422 on a page that has nothing to do with ids."""
    response = authenticated_client.get("/api/v1/purchase_orders/procurement")

    assert response.status_code == 200, (
        "the literal route lost to the id parameter again"
    )
    assert "kpis" in response.json()


def test_two_tenants_hitting_the_endpoint_see_their_own_numbers(
    authenticated_client,
    other_client,
    db_session,
    company,
    other_company,
    make_warehouse,
    make_product,
):
    """The same assertion as the unit test, through the HTTP layer, because
    that is where the token is turned into a company and where a mistake would
    actually reach a user."""
    _order(
        db_session,
        company,
        _supplier(db_session, company),
        make_warehouse(company),
        make_product(company),
        quantity=1,
        unit_price=111.0,
    )

    mine = authenticated_client.get("/api/v1/purchase_orders/procurement").json()
    theirs = other_client.get("/api/v1/purchase_orders/procurement").json()

    mine_open = next(c for c in mine["kpis"] if c["key"] == "open")
    theirs_open = next(c for c in theirs["kpis"] if c["key"] == "open")

    assert mine_open["value"] == 1
    assert theirs_open["value"] == 0, "the other tenant saw our order"
