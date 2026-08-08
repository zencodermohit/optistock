import logging

from etl.extract import extract_products_data, extract_sales_data
from etl.load import load_to_data_lake
from etl.transform import transform_sales_to_star_schema

logger = logging.getLogger(__name__)


def run_nightly_etl(engine=None, data_lake_dir: str | None = None) -> str:
    """Extract completed sales, denormalise them, and write Parquet.

    Returns the path of the file written.

    This used to catch every exception, log it, and return normally — so a broken
    pipeline looked identical to a successful one from the scheduler's point of
    view, and nobody would notice until the dashboards quietly stopped moving.
    Failures are now logged AND re-raised so the caller can alert on them.
    """
    logger.info("=== STARTING NIGHTLY ETL PIPELINE ===")

    try:
        sales_df = extract_sales_data(engine)
        products_df = extract_products_data(engine)

        fact_sales = transform_sales_to_star_schema(sales_df, products_df)

        path = load_to_data_lake(fact_sales, "fact_sales", data_lake_dir)

        logger.info(
            f"=== ETL PIPELINE COMPLETED SUCCESSFULLY ({len(fact_sales)} rows) ==="
        )
        return path
    except Exception:
        logger.exception("ETL pipeline failed")
        raise
