"""Analytics tests: the recommendations API plus the pure optimisation maths.

The EOQ and safety-stock functions had no tests at all, because nothing in the
application calls them yet. They are pure functions with published formulas, so
they are cheap to pin down now — before they get wired into the scheduler.
"""

import math

import pytest

from app.modules.analytics.eoq import calculate_eoq, calculate_safety_stock


# ---------------------------------------------------------------------------
# Recommendations API
# ---------------------------------------------------------------------------
def test_list_recommendations_requires_authentication(client):
    assert client.get("/api/v1/recommendations/").status_code == 401


def test_list_recommendations_returns_a_paginated_envelope(authenticated_client):
    response = authenticated_client.get("/api/v1/recommendations/")

    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "skip": 0, "limit": 50, "data": []}


def test_create_and_read_back_a_recommendation(
    authenticated_client, company, make_product, make_warehouse
):
    product = make_product(company)
    warehouse = make_warehouse(company)

    created = authenticated_client.post(
        "/api/v1/recommendations/",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "suggested_action": "reorder",
            "suggested_quantity": 120,
            "confidence_score": 87,
            "evidence": {"avg_daily_sales": 17.2, "forecast_period_days": 7},
            "business_reasoning": "Velocity of 17.2 units/day implies 120 units over the next week.",
        },
    )

    assert created.status_code == 201
    assert created.json()["evidence"]["avg_daily_sales"] == 17.2

    listed = authenticated_client.get("/api/v1/recommendations/")
    assert listed.json()["total"] == 1


def test_cannot_create_a_recommendation_against_another_tenants_product(
    authenticated_client, other_company, make_product, make_warehouse
):
    product = make_product(other_company)
    warehouse = make_warehouse(other_company)

    response = authenticated_client.post(
        "/api/v1/recommendations/",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "suggested_action": "reorder",
            "suggested_quantity": 10,
            "confidence_score": 50,
            "evidence": {},
            "business_reasoning": "Should never be created across a tenant boundary.",
        },
    )

    assert response.status_code == 400
    assert "active company" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Economic Order Quantity — EOQ = sqrt(2DS / H)
# ---------------------------------------------------------------------------
def test_eoq_matches_the_textbook_formula():
    # D=1000 units/yr, S=50 per order, H=2 per unit/yr -> sqrt(100000/2) = ~223.6
    assert calculate_eoq(1000, 50, 2) == pytest.approx(math.sqrt(50000))


def test_eoq_grows_with_demand():
    assert calculate_eoq(4000, 50, 2) > calculate_eoq(1000, 50, 2)


def test_eoq_shrinks_as_holding_cost_rises():
    assert calculate_eoq(1000, 50, 8) < calculate_eoq(1000, 50, 2)


@pytest.mark.parametrize(
    "demand, order_cost, holding_cost",
    [
        (0, 50, 2),  # zero demand
        (-100, 50, 2),  # negative demand
        (1000, -1, 2),  # negative order cost
        (1000, 50, 0),  # zero holding cost would divide by zero
    ],
)
def test_eoq_rejects_invalid_inputs(demand, order_cost, holding_cost):
    with pytest.raises(ValueError):
        calculate_eoq(demand, order_cost, holding_cost)


# ---------------------------------------------------------------------------
# Safety stock = (max daily * max lead) - (avg daily * avg lead)
# ---------------------------------------------------------------------------
def test_safety_stock_covers_the_gap_between_worst_and_average_case():
    # (20 * 10) - (10 * 5) = 150
    assert calculate_safety_stock(20, 10, 10, 5) == pytest.approx(150.0)


def test_safety_stock_is_never_negative():
    """When the worst case is no worse than average, buffer stock is zero."""
    assert calculate_safety_stock(5, 2, 10, 5) == 0.0
