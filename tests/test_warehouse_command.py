"""Zones, and the two layers of the Inventory module.

The interesting property is that zone membership is DERIVED. A stock line is in
Zone B because the product is furniture, so these tests are mostly about that
join behaving the way the docstring claims: recategorise a product and it moves
zone, with no backfill and no second source of truth.
"""

import pytest

from app.modules.warehouses.command import (
    ZONE_CRITICAL,
    ZONE_WARN,
    command_center,
    network,
)
from app.modules.warehouses.zone_models import WarehouseZone


@pytest.fixture
def zoned(db_session, company, make_warehouse):
    """A warehouse with two zones sized so utilisation is easy to reason about."""
    warehouse = make_warehouse(company, name="Zoned Depot", capacity_units=1000)
    db_session.add_all(
        [
            WarehouseZone(
                company_id=company.id,
                warehouse_id=warehouse.id,
                code="A",
                name="Electronics",
                category="Electronics",
                capacity_units=100,
            ),
            WarehouseZone(
                company_id=company.id,
                warehouse_id=warehouse.id,
                code="B",
                name="Furniture",
                category="Furniture",
                capacity_units=200,
            ),
        ]
    )
    db_session.flush()
    return warehouse


def _zone(data, code):
    return next(z for z in data["zones"] if z["code"] == code)


# ---------------------------------------------------------------------------
# Membership is derived, not assigned
# ---------------------------------------------------------------------------
def test_a_line_lands_in_the_zone_matching_its_category(
    db_session, company, zoned, make_product, make_stock
):
    tv = make_product(company, sku="Z-ELEC", name="Monitor")
    tv.category = "Electronics"
    desk = make_product(company, sku="Z-FURN", name="Desk")
    desk.category = "Furniture"
    make_stock(tv, zoned, quantity=40)
    make_stock(desk, zoned, quantity=90)
    db_session.commit()

    data = command_center(db_session, company.id, zoned.id)

    assert _zone(data, "A")["units_held"] == 40
    assert _zone(data, "B")["units_held"] == 90
    assert _zone(data, "A")["stock_lines"] == 1


def test_recategorising_a_product_moves_it_between_zones(
    db_session, company, zoned, make_product, make_stock
):
    """The whole argument for deriving membership instead of storing it. No
    backfill, no migration, and the two can never disagree."""
    product = make_product(company, sku="Z-MOVE")
    product.category = "Electronics"
    make_stock(product, zoned, quantity=50)
    db_session.commit()

    assert (
        _zone(command_center(db_session, company.id, zoned.id), "A")["units_held"] == 50
    )

    product.category = "Furniture"
    db_session.commit()

    after = command_center(db_session, company.id, zoned.id)
    assert _zone(after, "A")["units_held"] == 0
    assert _zone(after, "B")["units_held"] == 50


def test_a_category_with_no_zone_is_simply_not_shown(
    db_session, company, zoned, make_product, make_stock
):
    """Stock in a category the warehouse has no zone for still exists and still
    counts toward the building; it just has no bay on the floor plan."""
    orphan = make_product(company, sku="Z-ORPHAN")
    orphan.category = "Packaging"
    make_stock(orphan, zoned, quantity=70)
    db_session.commit()

    data = command_center(db_session, company.id, zoned.id)

    assert [z["code"] for z in data["zones"]] == ["A", "B"]
    assert sum(z["units_held"] for z in data["zones"]) == 0
    # The warehouse total is the truth about the building, zones or not.
    assert data["warehouse"]["units_held"] == 70


# ---------------------------------------------------------------------------
# Utilisation and state
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "quantity,expected",
    [(50, "ok"), (75, "warning"), (95, "critical"), (140, "critical")],
)
def test_zone_state_follows_utilisation(
    quantity, expected, db_session, company, zoned, make_product, make_stock
):
    product = make_product(company, sku=f"Z-STATE-{quantity}")
    product.category = "Electronics"
    make_stock(product, zoned, quantity=quantity)
    db_session.commit()

    zone = _zone(command_center(db_session, company.id, zoned.id), "A")

    assert zone["state"] == expected
    assert zone["utilisation"] == pytest.approx(quantity / 100)


def test_an_overfull_zone_reports_past_one_hundred(
    db_session, company, zoned, make_product, make_stock
):
    """Not clamped. A zone holding more than it was allocated is the single
    most useful thing this screen can say, and rounding it down to 100% would
    hide exactly that."""
    product = make_product(company, sku="Z-OVER")
    product.category = "Electronics"
    make_stock(product, zoned, quantity=175)
    db_session.commit()

    zone = _zone(command_center(db_session, company.id, zoned.id), "A")

    assert zone["utilisation"] == 1.75
    assert zone["available"] == 0


def test_the_thresholds_are_the_documented_ones():
    assert ZONE_WARN == 0.70
    assert ZONE_CRITICAL == 0.90


def test_a_zone_lists_only_the_lines_needing_attention(
    db_session, company, zoned, make_product, make_stock
):
    """Not the whole zone. A person walking the floor wants the six shelves
    that need them, not the eighty that do not."""
    healthy = make_product(company, sku="Z-OK")
    healthy.category = "Electronics"
    hs = make_stock(healthy, zoned, quantity=50)
    hs.reorder_point = 5

    low = make_product(company, sku="Z-LOW")
    low.category = "Electronics"
    ls = make_stock(low, zoned, quantity=3)
    ls.reorder_point = 20

    out = make_product(company, sku="Z-OUT")
    out.category = "Electronics"
    make_stock(out, zoned, quantity=0)
    db_session.commit()

    zone = _zone(command_center(db_session, company.id, zoned.id), "A")
    flagged = {line["sku"]: line["state"] for line in zone["attention"]}

    assert flagged == {"Z-OUT": "out", "Z-LOW": "low"}
    assert zone["stock_lines"] == 3


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------
def test_the_network_bands_each_site_by_health(
    db_session, company, make_warehouse, make_product, make_stock
):
    good = make_warehouse(company, name="Good Site", capacity_units=500)
    bad = make_warehouse(company, name="Bad Site", capacity_units=500)
    for i in range(4):
        p = make_product(company, sku=f"NET-OK-{i}")
        make_stock(p, good, quantity=100)
    for i in range(4):
        p = make_product(company, sku=f"NET-BAD-{i}")
        make_stock(p, bad, quantity=0)
    db_session.commit()

    data = network(db_session, company.id)
    by_name = {n["name"]: n for n in data["nodes"]}

    assert by_name["Good Site"]["band"] == "healthy"
    assert by_name["Bad Site"]["band"] == "at_risk"
    assert by_name["Bad Site"]["out_lines"] == 4


def test_only_transfers_still_in_flight_become_edges(
    db_session, company, make_warehouse
):
    """A completed transfer is history. Drawing it on a live map would show
    stock moving that arrived last week."""
    from app.modules.transfers.models import Transfer

    a = make_warehouse(company, name="Edge A")
    b = make_warehouse(company, name="Edge B")
    db_session.add_all(
        [
            Transfer(
                company_id=company.id,
                source_warehouse_id=a.id,
                destination_warehouse_id=b.id,
                status="pending",
            ),
            Transfer(
                company_id=company.id,
                source_warehouse_id=b.id,
                destination_warehouse_id=a.id,
                status="completed",
            ),
        ]
    )
    db_session.commit()

    data = network(db_session, company.id)

    assert len(data["edges"]) == 1
    assert data["summary"]["in_flight"] == 1
    # Both still appear in the history list.
    assert len(data["transfers"]) == 2


def test_accuracy_is_unmeasured_rather_than_perfect(
    db_session, company, make_warehouse
):
    """Nobody has counted anything. Reporting 100% would claim a measurement
    that was never taken."""
    make_warehouse(company)
    db_session.commit()

    summary = network(db_session, company.id)["summary"]

    assert summary["counts_recorded"] == 0


def test_both_layers_are_scoped_to_the_company(
    db_session, company, other_company, make_warehouse, zoned
):
    make_warehouse(other_company, name="Their Depot")
    db_session.commit()

    mine = network(db_session, company.id)

    assert "Their Depot" not in [n["name"] for n in mine["nodes"]]
    # And another tenant cannot open my command center.
    assert command_center(db_session, other_company.id, zoned.id) is None


def test_an_unknown_warehouse_returns_nothing(db_session, company):
    import uuid

    assert command_center(db_session, company.id, uuid.uuid4()) is None
