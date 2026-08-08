import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Columns every downstream analytic depends on. Asserted explicitly so a change
# to the extract queries fails here, loudly, instead of producing a Parquet file
# that silently lacks the tenant key.
REQUIRED_FACT_COLUMNS = (
    "company_id",
    "warehouse_id",
    "product_id",
    "sale_date",
    "quantity",
    "total_revenue",
)

# Parquet has no native UUID type. Left as Python uuid.UUID objects these get
# serialised as raw binary and come back as bytes, which then fail against a
# Postgres uuid column with "operator does not exist: uuid = bytea". Storing
# them as strings keeps the round trip lossless and the files portable to
# Power BI and other readers.
ID_COLUMNS = ("sale_id", "company_id", "customer_id", "warehouse_id", "product_id")


def transform_sales_to_star_schema(
    sales_df: pd.DataFrame, products_df: pd.DataFrame
) -> pd.DataFrame:
    """Denormalise sales + products into a single Fact_Sales table for analytics."""
    logger.info("[ETL - TRANSFORM] Joining Sales and Products data...")

    if sales_df.empty:
        logger.warning("[ETL - TRANSFORM] No completed sales to transform.")
        return pd.DataFrame(columns=list(REQUIRED_FACT_COLUMNS))

    fact_sales = pd.merge(sales_df, products_df, on="product_id", how="left")

    # Postgres NUMERIC arrives as Decimal, which Pandas cannot do arithmetic on.
    fact_sales["unit_price"] = fact_sales["unit_price"].astype(float)
    fact_sales["unit_cost"] = fact_sales["unit_cost"].astype(float)
    fact_sales["quantity"] = fact_sales["quantity"].astype(int)

    logger.info("[ETL - TRANSFORM] Calculating Total Revenue and Profit Margins...")
    fact_sales["total_revenue"] = fact_sales["quantity"] * fact_sales["unit_price"]
    fact_sales["total_cost"] = fact_sales["quantity"] * fact_sales["unit_cost"]
    fact_sales["profit_margin"] = fact_sales["total_revenue"] - fact_sales["total_cost"]

    for column in ID_COLUMNS:
        if column in fact_sales.columns:
            fact_sales[column] = fact_sales[column].astype(str)

    missing = [c for c in REQUIRED_FACT_COLUMNS if c not in fact_sales.columns]
    if missing:
        raise ValueError(f"Fact table is missing required columns: {missing}")

    return fact_sales
