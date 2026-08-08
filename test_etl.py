from etl.pipeline import run_nightly_etl
import pandas as pd
import glob
import os

print("Forcing the ETL pipeline to run right now...")
run_nightly_etl()

print("\n--- Verifying Data Lake Output ---")
# Find the newest parquet file in the data_lake folder
list_of_files = glob.glob('data_lake/*.parquet')
if not list_of_files:
    print("Error: No parquet files found!")
else:
    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"Reading Data Lake file: {latest_file}")
    
    # Read the highly-compressed parquet file back into Pandas
    df = pd.read_parquet(latest_file)
    
    print("\n[SUCCESS] The Star Schema looks like this:")
    print(df.dtypes)
    print(f"\n[SUCCESS] Total rows loaded for Machine Learning: {len(df)}")