from app.modules.analytics.forecast import run_demand_forecast
import pandas as pd

# Set Pandas to show the full text of our "reasoning" column so it doesn't get cut off!
pd.set_option('display.max_colwidth', None)

print("Running Demand Forecasting Engine on the Data Lake...")
result_df = run_demand_forecast()

if result_df is not None and not result_df.empty:
    print("\n--- 7-Day Demand Forecasts ---")
    print(result_df[['product_id', 'suggested_quantity', 'business_reasoning']].head(10))
else:
    print("No data to process.")