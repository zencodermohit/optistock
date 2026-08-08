"""ABC inventory classification.

Pareto ranking of products by revenue contribution:
  A — the products making up the first 80% of revenue (tight control)
  B — the next 15%
  C — the long tail

The ranking is computed WITHIN each tenant. Doing it globally, as the original
implementation did, would let a large tenant's catalogue dominate the cumulative
curve and push every product belonging to a smaller tenant into class C.
"""

import logging

import pandas as pd

from app.modules.analytics.data_lake import read_latest_fact_sales

logger = logging.getLogger(__name__)

A_THRESHOLD = 0.80
B_THRESHOLD = 0.95

RESULT_COLUMNS = [
    "company_id",
    "product_id",
    "total_revenue",
    "cumulative_percent",
    "abc_class",
]


def _classify(entry_percent: float) -> str:
    """Classify by where a product STARTS on the cumulative curve.

    Classifying on the cumulative percentage *after* adding the product — as the
    original did — judges the first row by its own share. A tenant whose best
    seller is 99% of revenue had that product land at cumulative 0.99 and get
    labelled C, the exact opposite of the truth. Using the entry point instead
    means the highest-revenue product is always A, which is what ABC means.
    """
    if entry_percent < A_THRESHOLD:
        return "A"
    if entry_percent < B_THRESHOLD:
        return "B"
    return "C"


def run_abc_analysis(data_lake_dir: str | None = None) -> pd.DataFrame:
    """Classify each tenant's products by revenue contribution."""
    logger.info("[ANALYTICS] Starting ABC Analysis...")

    df = read_latest_fact_sales(data_lake_dir)
    if df.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    revenue = (
        df.groupby(["company_id", "product_id"], as_index=False)["total_revenue"]
        .sum()
        .sort_values(["company_id", "total_revenue"], ascending=[True, False])
    )

    # Cumulative share is computed per tenant, so each company gets its own curve.
    grouped = revenue.groupby("company_id")["total_revenue"]
    revenue["cumulative_revenue"] = grouped.cumsum()
    revenue["company_total"] = grouped.transform("sum")
    revenue["cumulative_percent"] = (
        revenue["cumulative_revenue"] / revenue["company_total"]
    )
    # Share of revenue accounted for by everything ranked ABOVE this product.
    revenue["entry_percent"] = (
        revenue["cumulative_revenue"] - revenue["total_revenue"]
    ) / revenue["company_total"]
    revenue["abc_class"] = revenue["entry_percent"].apply(_classify)

    logger.info(
        f"[ANALYTICS] ABC Analysis classified {len(revenue)} products "
        f"across {revenue['company_id'].nunique()} tenants."
    )
    return revenue[RESULT_COLUMNS].reset_index(drop=True)
