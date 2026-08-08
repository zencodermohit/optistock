"""Shared pytest fixtures for the OptiStock test suite.

Design notes
------------
1. Tests run against a DEDICATED database (``optistock_test``), never the
   development database. ``DATABASE_URL`` is overwritten below *before* any
   application module is imported, so there is no code path that can reach the
   dev database even by accident.

2. Each test runs inside a transaction that is rolled back on teardown. The
   session uses ``join_transaction_mode="create_savepoint"``, which turns the
   application's own ``db.commit()`` calls into savepoint releases rather than
   real commits. Production commit behaviour is therefore exercised honestly,
   while the outer rollback still leaves the database pristine for the next test.

3. ``client`` and ``authenticated_client`` are SEPARATE TestClient instances.
   The previous conftest mutated a shared module-scoped client's headers, which
   silently authenticated every later test in the file and made the
   "unauthorized" tests pass only because of collection order.

4. TestClient is constructed WITHOUT the ``with`` block on purpose. Entering the
   context manager fires FastAPI startup events, which start the APScheduler
   background threads and register cron jobs. Tests neither need nor want that.
"""

import os
import uuid

# --- must happen before any `app.*` import -----------------------------------
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://optistock:optistock_password@127.0.0.1:5433/optistock_test",
)
# Forced, not defaulted: guarantees the suite can never point at the dev database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# The app refuses to boot without a signing key; supply a throwaway one for tests
# if the developer has not exported a real one.
os.environ.setdefault("SECRET_KEY", "test-only-signing-key-not-for-production")
# -----------------------------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.companies.models import Company  # noqa: E402
from app.modules.inventory.models import Inventory  # noqa: E402
from app.modules.products.models import Product  # noqa: E402
from app.modules.sales.models import Customer  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from app.modules.warehouses.models import Warehouse  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _short_id() -> str:
    """Short random suffix for columns carrying a global UNIQUE index."""
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Database bootstrap (session-scoped, runs once)
# ---------------------------------------------------------------------------
def _ensure_test_database_exists() -> None:
    """Create the test database if it is not there yet."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def _run_migrations() -> None:
    """Bring the test database up to head using the real Alembic migrations.

    Using the migrations rather than ``Base.metadata.create_all`` is deliberate:
    it means the tests exercise the schema that production actually gets,
    including anything the models declare but the migrations forgot to create.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine():
    _ensure_test_database_exists()
    _run_migrations()
    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """A session wrapped in a transaction that is always rolled back.

    The application commits freely inside this; ``create_savepoint`` mode maps
    those commits onto savepoints so the outer transaction stays in control.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Off by default so unrelated tests are not throttled into flakiness.

    Every TestClient request arrives from the same address, so a suite that
    exercises login several times would trip the 5/minute limit and fail for a
    reason having nothing to do with what it was testing. Tests that care about
    the limit ask for `enforced_rate_limiting` instead.
    """
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


@pytest.fixture
def enforced_rate_limiting():
    """Turn the limiter back on for tests that assert throttling behaviour."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------
@pytest.fixture
def _db_override(db_session):
    """Point the app's get_db dependency at the rolled-back test session."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(_db_override):
    """Unauthenticated client. Carries no Authorization header, ever."""
    return TestClient(app)


@pytest.fixture
def authenticated_client(_db_override, auth_headers):
    """Client for an admin of the primary test tenant."""
    return TestClient(app, headers=auth_headers)


@pytest.fixture
def other_client(_db_override, other_auth_headers):
    """Client for an admin of a DIFFERENT tenant, for isolation tests."""
    return TestClient(app, headers=other_auth_headers)


# ---------------------------------------------------------------------------
# Tenants and users
# ---------------------------------------------------------------------------
def _make_company(db_session, name: str) -> Company:
    company = Company(name=name)
    db_session.add(company)
    # commit(), not flush(): endpoints under test call db.rollback() on failure,
    # which in savepoint mode would otherwise discard the fixture data too and
    # make "state was left untouched" assertions meaningless. Committing releases
    # the savepoint; the outer transaction still rolls everything back on teardown.
    db_session.commit()
    return company


def _make_user(db_session, company: Company, role: str = "admin") -> User:
    user = User(
        email=f"{role}-{_short_id()}@example.com",
        hashed_password=get_password_hash("a-sufficiently-long-password"),
        company_id=company.id,
        role=role,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers_for(user: User) -> dict:
    token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role,
            "company_id": str(user.company_id),
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def company(db_session):
    return _make_company(db_session, "Acme Test Co")


@pytest.fixture
def admin_user(db_session, company):
    """A REAL user row. get_current_user resolves identity from the database,
    so a token minted for a non-existent id is now correctly rejected as 401."""
    return _make_user(db_session, company, role="admin")


@pytest.fixture
def auth_headers(admin_user):
    return _headers_for(admin_user)


@pytest.fixture
def other_company(db_session):
    return _make_company(db_session, "Globex Test Co")


@pytest.fixture
def other_admin_user(db_session, other_company):
    return _make_user(db_session, other_company, role="admin")


@pytest.fixture
def other_auth_headers(other_admin_user):
    return _headers_for(other_admin_user)


@pytest.fixture
def analyst_headers(db_session, company):
    """Read-only role, for checking that write endpoints return 403."""
    return _headers_for(_make_user(db_session, company, role="analyst"))


# ---------------------------------------------------------------------------
# Domain object factories
# ---------------------------------------------------------------------------
@pytest.fixture
def make_product(db_session):
    def _make(company, sku=None, name="Test Widget", unit_cost=10, selling_price=25):
        product = Product(
            company_id=company.id,
            sku=sku or f"SKU-{_short_id()}",
            name=name,
            category="test",
            unit_cost=unit_cost,
            selling_price=selling_price,
            status="active",
        )
        db_session.add(product)
        db_session.commit()
        return product

    return _make


@pytest.fixture
def make_warehouse(db_session):
    def _make(company, name="Test Warehouse", capacity_units=1000):
        warehouse = Warehouse(
            company_id=company.id,
            name=name,
            location_code=f"WH-{_short_id()}",
            capacity_units=capacity_units,
            is_active=True,
        )
        db_session.add(warehouse)
        db_session.commit()
        return warehouse

    return _make


@pytest.fixture
def make_customer(db_session):
    def _make(company, name="Test Customer"):
        customer = Customer(
            company_id=company.id,
            name=name,
            email=f"cust-{_short_id()}@example.com",
            is_active=True,
        )
        db_session.add(customer)
        db_session.commit()
        return customer

    return _make


@pytest.fixture
def make_stock(db_session):
    def _make(product, warehouse, quantity):
        inventory = Inventory(
            product_id=product.id, warehouse_id=warehouse.id, quantity=quantity
        )
        db_session.add(inventory)
        db_session.commit()
        return inventory

    return _make
