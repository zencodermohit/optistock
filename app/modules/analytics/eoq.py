import math


def calculate_eoq(
    annual_demand: float, order_cost: float, holding_cost_per_unit: float
) -> float:
    """
    Calculates the Economic Order Quantity (EOQ).

    Formula: EOQ = sqrt( (2 * D * S) / H )
    Where:
        D = Annual Demand (units)
        S = Cost per order (fixed cost, e.g., shipping, handling)
        H = Holding cost per unit per year

    Returns:
        The optimal number of units to order to minimize total inventory costs.
    """
    if annual_demand <= 0 or order_cost < 0 or holding_cost_per_unit <= 0:
        raise ValueError("Invalid parameters for EOQ calculation.")

    return math.sqrt((2 * annual_demand * order_cost) / holding_cost_per_unit)


def calculate_safety_stock(
    max_daily_demand: float,
    max_lead_time_days: float,
    avg_daily_demand: float,
    avg_lead_time_days: float,
) -> float:
    """
    Calculates the Safety Stock using the standard formula.

    Formula: Safety Stock = (Max Daily Demand * Max Lead Time) - (Avg Daily Demand * Avg Lead Time)
    """
    max_usage = max_daily_demand * max_lead_time_days
    avg_usage = avg_daily_demand * avg_lead_time_days

    safety_stock = max_usage - avg_usage
    return max(0.0, safety_stock)  # Cannot be negative
