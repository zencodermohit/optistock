import logging
import os
from datetime import datetime, timezone

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)


def load_to_data_lake(
    df: pd.DataFrame, dataset_name: str, data_lake_dir: str | None = None
) -> str:
    """Write the cleaned DataFrame to the data lake as Parquet.

    Returns the path written, so callers and tests do not have to re-derive it.
    """
    directory = data_lake_dir or settings.DATA_LAKE_DIR
    # The directory previously had to pre-exist; a fresh container or a wiped
    # volume would make the nightly job fail on its very first write.
    os.makedirs(directory, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    path = os.path.join(directory, f"{dataset_name}_{today}.parquet")

    logger.info(f"[ETL - LOAD] Saving {len(df)} rows to {path}...")

    # Parquet is columnar: far smaller on disk and much faster for the
    # single-column scans the analytics layer does.
    df.to_parquet(path, index=False)

    logger.info("[ETL - LOAD] Successfully written to Data Lake!")
    return path
