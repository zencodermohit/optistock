"""Cross-tenant isolation.

OptiStock is a shared-database, shared-schema multi-tenant system: Acme's rows
and Globex's rows live side by side in the same tables, separated only by a
company_id filter in application code. Miss one filter and it is a data breach,
not a bug. These tests approach every reachable surface from the WRONG tenant
and require it to be refused.
"""

from app.core.security import create_access_token
from app.modules.inventory.models import Inventory


def test_cannot_read_another_tenants_product_by_id(
    authenticated_client, other_company, make_product
):
    foreign = make_product(other_company, name="Globex Secret Widget")

    response = authenticated_client.get(f"/api/v1/products/{foreign.id}")

    # 404, not 403: we must not confirm that the id exists at all.
    assert response.status_code == 404


def test_cannot_read_another_tenants_warehouse_by_id(
    authenticated_client, other_company, make_warehouse
):
    foreign = make_warehouse(other_company, name="Globex Depot")

    assert (
        authenticated_client.get(f"/api/v1/warehouses/{foreign.id}").status_code == 404
    )


def test_cannot_update_another_tenants_product(
    authenticated_client, other_company, make_product
):
    foreign = make_product(other_company)

    response = authenticated_client.put(
        f"/api/v1/products/{foreign.id}",
        json={"name": "Renamed By An Outsider"},
    )
    assert response.status_code == 404


def test_cannot_archive_another_tenants_product(
    authenticated_client, other_company, make_product
):
    foreign = make_product(other_company)

    assert (
        authenticated_client.delete(f"/api/v1/products/{foreign.id}").status_code == 404
    )


def test_cannot_adjust_stock_for_another_tenants_product(
    authenticated_client,
    db_session,
    other_company,
    make_product,
    make_warehouse,
    make_stock,
):
    foreign_product = make_product(other_company)
    foreign_warehouse = make_warehouse(other_company)
    make_stock(foreign_product, foreign_warehouse, quantity=500)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(foreign_product.id),
            "warehouse_id": str(foreign_warehouse.id),
            "quantity_change": -500,
            "reason": "attempted cross-tenant theft",
        },
    )

    assert response.status_code == 400
    assert "active company" in response.json()["detail"]

    db_session.expire_all()
    untouched = (
        db_session.query(Inventory.quantity)
        .filter(Inventory.product_id == foreign_product.id)
        .scalar()
    )
    assert untouched == 500


def test_cannot_mix_own_product_with_another_tenants_warehouse(
    authenticated_client, company, other_company, make_product, make_warehouse
):
    """Both ends of the relationship must be checked, not just one.

    Verifying only the product would let a caller pair their own product with a
    foreign warehouse and learn things about another tenant's facilities.
    """
    own_product = make_product(company)
    foreign_warehouse = make_warehouse(other_company)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(own_product.id),
            "warehouse_id": str(foreign_warehouse.id),
            "quantity_change": 10,
            "reason": "mixed tenant references",
        },
    )
    assert response.status_code == 400


def test_cannot_sell_to_another_tenants_customer(
    authenticated_client,
    company,
    other_company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    foreign_customer = make_customer(other_company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=100)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(foreign_customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 1, "unit_price": 5.0}
            ],
        },
    )

    assert response.status_code == 400
    assert "active company" in response.json()["detail"]


def test_cannot_sell_another_tenants_product(
    authenticated_client,
    company,
    other_company,
    make_customer,
    make_warehouse,
    make_product,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    foreign_product = make_product(other_company)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {
                    "product_id": str(foreign_product.id),
                    "quantity": 1,
                    "unit_price": 5.0,
                }
            ],
        },
    )
    assert response.status_code == 400


def test_inventory_listing_excludes_other_tenants_stock(
    authenticated_client,
    company,
    other_company,
    make_product,
    make_warehouse,
    make_stock,
):
    own_product = make_product(company)
    own_warehouse = make_warehouse(company)
    make_stock(own_product, own_warehouse, quantity=7)

    foreign_product = make_product(other_company)
    foreign_warehouse = make_warehouse(other_company)
    make_stock(foreign_product, foreign_warehouse, quantity=999)

    response = authenticated_client.get("/api/v1/inventory/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["quantity"] == 7


def test_each_tenant_sees_only_its_own_sales(
    authenticated_client,
    other_client,
    company,
    other_company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    def place_sale(http_client, tenant):
        customer = make_customer(tenant)
        warehouse = make_warehouse(tenant)
        product = make_product(tenant)
        make_stock(product, warehouse, quantity=10)
        return http_client.post(
            "/api/v1/sales/",
            json={
                "customer_id": str(customer.id),
                "source_warehouse_id": str(warehouse.id),
                "items": [
                    {"product_id": str(product.id), "quantity": 2, "unit_price": 11.0}
                ],
            },
        )

    assert place_sale(authenticated_client, company).status_code == 201
    assert place_sale(other_client, other_company).status_code == 201

    mine = authenticated_client.get("/api/v1/sales/").json()
    theirs = other_client.get("/api/v1/sales/").json()

    assert mine["total"] == 1
    assert theirs["total"] == 1
    assert mine["data"][0]["id"] != theirs["data"][0]["id"]


def test_two_tenants_may_use_the_same_sku(authenticated_client, other_client):
    """SKUs are namespaced per tenant, not globally.

    ProductRepository.get_by_sku filters by company_id and its docstring states
    "Two different companies can have a MUG-01". If the database instead carries
    a global UNIQUE index on sku, the first tenant to register a common code like
    "MUG-01" permanently denies it to every other tenant on the platform — and
    leaks the existence of their catalogue in the process.
    """
    payload = {
        "sku": "MUG-01",
        "name": "Coffee Mug",
        "unit_cost": 3,
        "selling_price": 9,
    }

    mine = authenticated_client.post("/api/v1/products/", json=payload)
    theirs = other_client.post("/api/v1/products/", json=payload)

    assert mine.status_code == 201
    assert (
        theirs.status_code == 201
    ), "second tenant was blocked from using a SKU the first tenant registered"
    assert mine.json()["id"] != theirs.json()["id"]


def test_two_tenants_may_use_the_same_warehouse_location_code(
    authenticated_client, other_client
):
    payload = {"name": "Main Depot", "location_code": "MAIN", "capacity_units": 100}

    mine = authenticated_client.post("/api/v1/warehouses/", json=payload)
    theirs = other_client.post("/api/v1/warehouses/", json=payload)

    assert mine.status_code == 201
    assert (
        theirs.status_code == 201
    ), "second tenant was blocked from using a location code the first registered"


def test_a_token_whose_company_claim_was_tampered_with_is_rejected(
    client, admin_user, other_company
):
    """get_current_user re-reads the tenant from the database, so a forged (but
    correctly signed) company_id claim must not grant access to that tenant."""
    tampered = create_access_token(
        {
            "sub": str(admin_user.id),
            "role": "admin",
            "company_id": str(other_company.id),
        }
    )

    response = client.get(
        "/api/v1/products/", headers={"Authorization": f"Bearer {tampered}"}
    )
    assert response.status_code == 401


def test_a_deactivated_user_loses_access_immediately(client, db_session, admin_user):
    """Tokens live for an hour; deactivation must take effect on the next request."""
    token = create_access_token(
        {
            "sub": str(admin_user.id),
            "role": admin_user.role,
            "company_id": str(admin_user.company_id),
        }
    )
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/products/", headers=headers).status_code == 200

    admin_user.is_active = False
    db_session.flush()

    assert client.get("/api/v1/products/", headers=headers).status_code == 401
