import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.database import engine as default_engine

logger = logging.getLogger(__name__)


def _read_sql(query: str, engine=None) -> pd.DataFrame:
    """Run a query and hand the rows to Pandas.

    The bind is injectable so tests can point the ETL at a fixture database
    rather than the module-level global. It accepts either an Engine or an
    already-open Connection — the latter lets a test run the ETL inside its own
    uncommitted transaction and still see the rows it staged.
    """
    bind = engine or default_engine

    if isinstance(bind, Connection):
        result = bind.execute(text(query))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    with bind.connect() as connection:
        result = connection.execute(text(query))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def extract_sales_data(engine=None) -> pd.DataFrame:
    """Pull completed sale lines.

    company_id is essential rather than decorative: the data lake holds every
    tenant's sales in a single file, so without it the downstream analytics
    cannot attribute a recommendation to the tenant it belongs to.
    """
    logger.info("[ETL - EXTRACT] Pulling sales data...")
    query = """
        SELECT
            s.id as sale_id,
            s.company_id,
            s.customer_id,
            s.source_warehouse_id as warehouse_id,
            s.status,
            s.created_at as sale_date,
            si.product_id,
            si.quantity,
            si.unit_price
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        WHERE s.status = 'completed'
    """
    return _read_sql(query, engine)


def extract_products_data(engine=None) -> pd.DataFrame:
    """Pull the product catalogue.

    Deliberately no company_id here — it arrives via the sales side of the join,
    and selecting it on both sides would leave Pandas with company_id_x/_y.
    """
    logger.info("[ETL - EXTRACT] Pulling product catalog...")
    query = "SELECT id as product_id, sku, name, category, unit_cost FROM products"
    return _read_sql(query, engine)
