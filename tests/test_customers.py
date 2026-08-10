"""Customer endpoints.

Until these existed the core revenue workflow could not be completed through the
API at all: a sale requires a customer_id and there was no way to create one
outside the seed script.
"""

from app.modules.sales.models import Customer


def test_list_customers_requires_authentication(client):
    assert client.get("/api/v1/customers/").status_code == 401


def test_create_customer(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/customers/",
        json={"name": "Acme Buyers Ltd", "email": "buying@acme.example.com"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Buyers Ltd"
    assert body["is_active"] is True


def test_create_customer_rejects_client_supplied_company_id(authenticated_client):
    """Tenant identity comes from the token, never the request body."""
    response = authenticated_client.post(
        "/api/v1/customers/",
        json={
            "name": "Sneaky Corp",
            "company_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert response.status_code == 422


def test_create_customer_rejects_malformed_email(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/customers/", json={"name": "Bad Email Co", "email": "not-an-email"}
    )
    assert response.status_code == 422


def test_email_is_optional(authenticated_client):
    """Walk-in and cash customers do not always have one."""
    response = authenticated_client.post(
        "/api/v1/customers/", json={"name": "Counter Sale"}
    )
    assert response.status_code == 201
    assert response.json()["email"] is None


def test_list_is_scoped_to_the_tenant(
    authenticated_client, company, other_company, make_customer
):
    make_customer(company, name="Mine")
    make_customer(other_company, name="Theirs")

    body = authenticated_client.get("/api/v1/customers/").json()

    assert body["total"] == 1
    assert [c["name"] for c in body["data"]] == ["Mine"]


def test_search_matches_name_or_email(authenticated_client, company, make_customer):
    make_customer(company, name="Zenith Traders")
    make_customer(company, name="Apex Industries")

    body = authenticated_client.get(
        "/api/v1/customers/", params={"search": "Zen"}
    ).json()

    assert body["total"] == 1
    assert body["data"][0]["name"] == "Zenith Traders"


def test_cannot_read_another_tenants_customer(
    authenticated_client, other_company, make_customer
):
    foreign = make_customer(other_company)

    # 404, not 403 — we must not confirm the id exists.
    assert (
        authenticated_client.get(f"/api/v1/customers/{foreign.id}").status_code == 404
    )


def test_cannot_update_another_tenants_customer(
    authenticated_client, other_company, make_customer
):
    foreign = make_customer(other_company)

    response = authenticated_client.patch(
        f"/api/v1/customers/{foreign.id}", json={"name": "Renamed By An Outsider"}
    )
    assert response.status_code == 404


def test_update_only_touches_fields_that_were_sent(
    authenticated_client, db_session, company, make_customer
):
    customer = make_customer(company, name="Original Name")
    original_email = customer.email

    response = authenticated_client.patch(
        f"/api/v1/customers/{customer.id}", json={"name": "New Name"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    assert response.json()["email"] == original_email


def test_delete_is_a_soft_delete(
    authenticated_client, db_session, company, make_customer
):
    """Sales reference customers; hard deletion would break history."""
    customer = make_customer(company)

    response = authenticated_client.delete(f"/api/v1/customers/{customer.id}")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert db_session.query(Customer).filter(Customer.id == customer.id).count() == 1


def test_analyst_cannot_create_customers(client, analyst_headers):
    response = client.post(
        "/api/v1/customers/", headers=analyst_headers, json={"name": "Nope"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Order history
# ---------------------------------------------------------------------------
def test_order_history_and_lifetime_value(
    authenticated_client,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=100)

    for _ in range(2):
        assert (
            authenticated_client.post(
                "/api/v1/sales/",
                json={
                    "customer_id": str(customer.id),
                    "source_warehouse_id": str(warehouse.id),
                    "items": [
                        {
                            "product_id": str(product.id),
                            "quantity": 2,
                            "unit_price": 25.0,
                        }
                    ],
                },
            ).status_code
            == 201
        )

    body = authenticated_client.get(f"/api/v1/customers/{customer.id}/orders").json()

    assert body["total"] == 2
    assert body["lifetime_value"] == 100.0  # 2 orders x 2 units x 25.00


def test_order_history_of_another_tenants_customer_is_not_reachable(
    authenticated_client, other_company, make_customer
):
    foreign = make_customer(other_company)
    assert (
        authenticated_client.get(f"/api/v1/customers/{foreign.id}/orders").status_code
        == 404
    )


# ---------------------------------------------------------------------------
# The directory read model
# ---------------------------------------------------------------------------
def test_the_directory_ranks_customers_by_what_they_are_worth(
    db_session, company, make_customer, make_warehouse, make_product, make_stock
):
    """Alphabetical order answers a question nobody arrived with."""
    from app.modules.customers.service import CustomerService
    from app.modules.sales.schemas import SaleCreate, SaleItemCreate
    from app.modules.sales.service import SaleService

    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=1000)

    big = make_customer(company, name="Alpha Big")
    small = make_customer(company, name="Zeta Small")
    sales = SaleService(db_session)
    for customer, quantity in ((small, 1), (big, 50)):
        sales.create_sale(
            SaleCreate(
                customer_id=customer.id,
                source_warehouse_id=warehouse.id,
                items=[
                    SaleItemCreate(product_id=product.id, quantity=quantity, unit_price=10.0)
                ],
            ),
            company.id,
        )
    db_session.commit()

    rows = CustomerService(db_session).directory(company.id)

    assert rows[0]["name"] == "Alpha Big"
    assert rows[0]["lifetime_value"] == 500.0
    assert rows[0]["orders"] == 1
    assert rows[0]["average_order_value"] == 500.0
    assert rows[0]["last_order_at"] is not None


def test_a_customer_who_never_ordered_still_appears(
    db_session, company, make_customer
):
    """A LEFT join, deliberately. Someone who has never ordered is the row worth
    a phone call, and an inner join would hide them."""
    from app.modules.customers.service import CustomerService

    make_customer(company, name="Never Ordered")
    db_session.commit()

    rows = CustomerService(db_session).directory(company.id)

    assert len(rows) == 1
    assert rows[0]["orders"] == 0
    assert rows[0]["lifetime_value"] == 0.0
    assert rows[0]["last_order_at"] is None
    # Not zero: an average of nothing is not 0, it does not exist.
    assert rows[0]["average_order_value"] is None


def test_the_directory_is_scoped_to_the_company(
    db_session, company, other_company, make_customer
):
    from app.modules.customers.service import CustomerService

    make_customer(company, name="Mine Only")
    make_customer(other_company, name="Theirs Only")
    db_session.commit()

    names = [r["name"] for r in CustomerService(db_session).directory(company.id)]

    assert names == ["Mine Only"]


def test_the_directory_can_be_searched(db_session, company, make_customer):
    from app.modules.customers.service import CustomerService

    make_customer(company, name="Findable Ltd")
    make_customer(company, name="Other Corp")
    db_session.commit()

    rows = CustomerService(db_session).directory(company.id, search="findable")

    assert [r["name"] for r in rows] == ["Findable Ltd"]


def test_directory_is_routed_above_the_id_lookup(authenticated_client):
    response = authenticated_client.get("/api/v1/customers/directory")

    assert response.status_code == 200
    assert "data" in response.json()
