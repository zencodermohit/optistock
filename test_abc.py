from app.modules.analytics.abc_analysis import run_abc_analysis

print("Running ABC Analysis on the Data Lake...")
result_df = run_abc_analysis()

if result_df is not None and not result_df.empty:
    print("\n--- ABC Classifications ---")
    # We print the top 10 products
    print(result_df[['product_id', 'total_revenue', 'cumulative_percent', 'abc_class']].head(10))
else:
    print("No data to process.")