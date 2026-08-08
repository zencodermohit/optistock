"""Shared access to the Parquet data lake."""

import glob
import logging
import os

import pandas as pd
import pyarrow.parquet as pq

from app.core.config import settings

logger = logging.getLogger(__name__)


# Columns the analytics layer cannot work without. Files written before the ETL
# carried a tenant key lack company_id, and reading one produced a bare
# `KeyError: 'company_id'` from deep inside a groupby.
REQUIRED_COLUMNS = frozenset({"company_id", "product_id", "quantity"})


def _fact_sales_files(data_lake_dir: str | None = None) -> list[str]:
    directory = data_lake_dir or settings.DATA_LAKE_DIR
    return sorted(
        glob.glob(os.path.join(directory, "fact_sales_*.parquet")),
        key=os.path.getctime,
        reverse=True,
    )


def latest_fact_sales_path(data_lake_dir: str | None = None) -> str | None:
    """Newest fact_sales file whose schema the analytics can actually use.

    Older files are skipped rather than failing the run: the lake accumulates
    history, and one stale file from a previous schema must not permanently
    break the nightly job.
    """
    for path in _fact_sales_files(data_lake_dir):
        columns = set(pq.read_schema(path).names)
        missing = REQUIRED_COLUMNS - columns
        if missing:
            logger.warning(
                f"[ANALYTICS] Skipping {path}: predates the current fact schema "
                f"(missing {sorted(missing)})."
            )
            continue
        return path
    return None


def read_latest_fact_sales(data_lake_dir: str | None = None) -> pd.DataFrame:
    """Load the newest usable fact table, or an empty frame if there is none.

    Returning an empty DataFrame rather than None means callers can treat "no
    data yet" and "data with no rows" identically instead of branching on type.
    """
    path = latest_fact_sales_path(data_lake_dir)
    if path is None:
        logger.warning("[ANALYTICS] No usable data lake file found. Run the ETL first.")
        return pd.DataFrame()

    logger.info(f"[ANALYTICS] Reading {path}")
    return pd.read_parquet(path)
