"""The compliance audit trail.

``AuditService.log_action`` existed, the table existed, the migration existed and
the admin read endpoint existed — but nothing in the entire codebase ever called
it, so the trail was permanently empty while looking fully built. Auditing is now
a flush-level listener, and these tests assert it fires on the paths that matter.
"""

from app.modules.audit.models import AuditLog


def _entries(db_session, entity=None, action=None):
    db_session.expire_all()
    query = db_session.query(AuditLog)
    if entity:
        query = query.filter(AuditLog.entity_name == entity)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.all()


# ---------------------------------------------------------------------------
# It actually records things now
# ---------------------------------------------------------------------------
def test_creating_a_product_is_recorded(authenticated_client, db_session, admin_user):
    response = authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-AUDIT-1",
            "name": "Audited Widget",
            "unit_cost": 5,
            "selling_price": 15,
        },
    )
    assert response.status_code == 201

    entry = next(e for e in _entries(db_session, "products", "CREATE"))
    assert str(entry.entity_id) == response.json()["id"]
    assert entry.user_id == admin_user.id
    assert entry.company_id == admin_user.company_id
    assert entry.new_values["sku"] == "SKU-AUDIT-1"
    assert entry.old_values is None


def test_updating_a_product_records_before_and_after(
    authenticated_client, db_session, company, make_product
):
    product = make_product(company, name="Original Name", selling_price=20)

    response = authenticated_client.put(
        f"/api/v1/products/{product.id}", json={"name": "Renamed"}
    )
    assert response.status_code == 200

    entry = next(e for e in _entries(db_session, "products", "UPDATE"))
    assert entry.old_values["name"] == "Original Name"
    assert entry.new_values["name"] == "Renamed"
    # Only the columns that actually changed are recorded.
    assert "selling_price" not in entry.new_values


def test_stock_adjustment_is_recorded(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """Stock movements are the single most audit-worthy thing in the system."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=100)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -30,
            "reason": "damaged in transit",
        },
    )
    assert response.status_code == 200

    entry = next(e for e in _entries(db_session, "inventory", "UPDATE"))
    assert entry.old_values["quantity"] == 100
    assert entry.new_values["quantity"] == 70


def test_a_sale_records_both_the_sale_and_the_stock_change(
    authenticated_client,
    db_session,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=50)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 5, "unit_price": 9.0}
            ],
        },
    )
    assert response.status_code == 201

    recorded = {e.entity_name for e in _entries(db_session)}
    assert "sales" in recorded
    assert "inventory" in recorded


def test_archiving_a_product_is_recorded_as_an_update(
    authenticated_client, db_session, company, make_product
):
    """Deletes here are soft, so the trail should show the status transition."""
    product = make_product(company)

    assert (
        authenticated_client.delete(f"/api/v1/products/{product.id}").status_code == 200
    )

    entry = next(e for e in _entries(db_session, "products", "UPDATE"))
    assert entry.old_values["status"] == "active"
    assert entry.new_values["status"] == "archived"


def test_a_purchasing_workflow_is_recorded_end_to_end(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """A listener is only worth having if it covers paths nobody wrote code for.

    This walks supplier -> purchase order -> delivery without any auditing code
    existing in those modules, and requires the trail to show all of it.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)

    supplier = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "Audited Supplier", "contact_email": "s@example.com"},
    )
    assert supplier.status_code == 201

    assert (
        authenticated_client.patch(
            f"/api/v1/suppliers/{supplier.json()['id']}",
            json={"name": "Renamed Supplier"},
        ).status_code
        == 200
    )

    po = authenticated_client.post(
        "/api/v1/purchase_orders/",
        json={
            "supplier_id": supplier.json()["id"],
            "destination_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 40, "unit_price": 3.0}
            ],
        },
    )
    assert po.status_code == 201

    assert (
        authenticated_client.patch(
            f"/api/v1/purchase_orders/{po.json()['id']}/deliver"
        ).status_code
        == 200
    )

    recorded = {(e.entity_name, e.action) for e in _entries(db_session)}

    assert ("suppliers", "CREATE") in recorded
    assert ("suppliers", "UPDATE") in recorded
    assert ("purchase_orders", "CREATE") in recorded
    assert ("purchase_orders", "UPDATE") in recorded  # draft -> delivered
    assert ("inventory", "UPDATE") in recorded  # stock received


def test_warehouse_changes_are_recorded(authenticated_client, db_session):
    created = authenticated_client.post(
        "/api/v1/warehouses/",
        json={"name": "Audited WH", "location_code": "WH-AUD-1", "capacity_units": 50},
    )
    assert created.status_code == 201

    entry = next(e for e in _entries(db_session, "warehouses", "CREATE"))
    assert entry.new_values["location_code"] == "WH-AUD-1"


# ---------------------------------------------------------------------------
# What it must NOT do
# ---------------------------------------------------------------------------
def test_a_rolled_back_change_leaves_no_audit_row(
    authenticated_client,
    db_session,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    """The trail must reflect what happened, not what was attempted.

    Audit rows are written in the same transaction as the change itself, so a
    failed sale takes its audit entries down with it.
    """
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=1)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 99, "unit_price": 9.0}
            ],
        },
    )
    assert response.status_code == 400

    assert _entries(db_session, "sales") == []
    assert _entries(db_session, "inventory") == []


def test_unauthenticated_activity_produces_no_audit_rows(client, db_session):
    client.get("/api/v1/products/")
    assert _entries(db_session) == []


def test_background_jobs_do_not_crash_for_lack_of_an_actor(
    db_session, company, make_product
):
    """Seed scripts, the ETL and the nightly analytics all write without a user.

    They must be skipped rather than raising, since there is nobody to attribute
    the change to.
    """
    make_product(company, name="Created with no HTTP actor")
    assert _entries(db_session) == []


def test_the_audit_table_does_not_audit_itself(authenticated_client, db_session):
    """A listener that recorded its own writes would recurse without limit."""
    authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-NOLOOP-1",
            "name": "No Loop",
            "unit_cost": 1,
            "selling_price": 2,
        },
    )
    assert _entries(db_session, "audit_logs") == []


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------
def test_admin_can_read_the_trail_through_the_api(authenticated_client):
    authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-READ-1",
            "name": "Readable",
            "unit_cost": 1,
            "selling_price": 3,
        },
    )

    response = authenticated_client.get("/api/v1/audit/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert body[0]["entity_name"] == "products"
    assert body[0]["action"] == "CREATE"


def test_non_admins_cannot_read_the_trail(client, analyst_headers):
    assert client.get("/api/v1/audit/", headers=analyst_headers).status_code == 403


def test_one_tenant_cannot_read_another_tenants_trail(
    authenticated_client, other_client, admin_user, other_admin_user
):
    authenticated_client.post(
        "/api/v1/products/",
        json={"sku": "SKU-MINE-1", "name": "Mine", "unit_cost": 1, "selling_price": 2},
    )
    other_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-THEIRS-1",
            "name": "Theirs",
            "unit_cost": 1,
            "selling_price": 2,
        },
    )

    mine = authenticated_client.get("/api/v1/audit/").json()
    theirs = other_client.get("/api/v1/audit/").json()

    assert [e["new_values"]["sku"] for e in mine] == ["SKU-MINE-1"]
    assert [e["new_values"]["sku"] for e in theirs] == ["SKU-THEIRS-1"]
    assert all(e["company_id"] == str(admin_user.company_id) for e in mine)
    assert all(e["company_id"] == str(other_admin_user.company_id) for e in theirs)


def test_the_trail_survives_deletion_of_the_user_who_made_the_change(
    authenticated_client, db_session, admin_user
):
    """user_id is ON DELETE SET NULL. Scoping the read through a join onto users
    meant removing an employee erased the readability of everything they did."""
    authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-GONE-1",
            "name": "Outlives Its Author",
            "unit_cost": 1,
            "selling_price": 2,
        },
    )
    company_id = admin_user.company_id

    db_session.execute(AuditLog.__table__.update().values(user_id=None))
    db_session.commit()

    surviving = (
        db_session.query(AuditLog).filter(AuditLog.company_id == company_id).all()
    )
    assert len(surviving) >= 1
    assert surviving[0].user_id is None
    assert surviving[0].company_id == company_id
